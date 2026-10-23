"""Codex mode: the local Codex CLI (`codex exec`) on the user's own ChatGPT subscription.

Codex is a coding agent, so every tool that could act is switched off for this call: shell, browser,
computer use, plugins and the rest that exist in the installed version; the sandbox is read-only and
the working folder is an empty temporary one. The CLI only reads images from files, so the screenshot
is written to a private temporary folder for the duration of the call and deleted afterwards, also
when the call fails or is cancelled. Only a ChatGPT login is accepted, never an API key.
"""
from __future__ import annotations

import logging
import os
import secrets
import shutil
import stat
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from .i18n import N_, tr
from . import claude_client
from .claude_client import ClaudeCall, ClaudeResult

# Features that let the agent act or reach outside this one answer. Only the ones the installed CLI
# knows are passed to --disable (an unknown name is an error).
RISKY_FEATURES = (
    "shell_tool", "unified_exec", "unified_exec_tty", "shell_snapshot", "browser_use", "browser_use_external",
    "browser_use_full_cdp_access", "browser_annotation_api", "computer_use", "apps", "plugins", "remote_plugin",
    "image_generation", "code_mode_host", "tool_suggest", "skill_search", "skill_mcp_dependency_install", "goals",
    "sleep_tool", "standalone_web_search", "web_search_request", "web_search_cached", "auth_elicitation",
)
CHATGPT_LOGIN = "Logged in using ChatGPT"
FOLDER_PREFIX = "desk-sister-codex-"
OUR_FILES = ("screen.jpg", "reply.txt")  # all a call ever writes into its folder
EFFORTS = {"haiku": "low", "sonnet": "medium"}  # the two tiers differ by reasoning effort on the account's model
TEMP_ROOT: Path | None = None  # None: the user's %TEMP%; tests point it elsewhere
log = logging.getLogger(__name__)
_pending: dict[Path, _Folder | _Recheck | None] = {}  # screenshot folders still to delete (held where possible)
_pending_lock = threading.Lock()
_worker: threading.Thread | None = None  # the one background cleanup thread
_wanted = False
_sweeps: list[Path | None] = []
_worker_lock = threading.Lock()
_STARTED = time.time()  # folders made after this belong to this run: a call may still be using them
INSTRUCTION = N_("（附图是主人当前窗口的截图。不要调用任何工具，只按上面的输出格式回答一行。）")


def find_codex(configured: str = "") -> str | None:
    """The native codex.exe only: a .cmd/.ps1 launcher would let cmd.exe reinterpret characters in our paths."""
    if configured:
        return configured if configured.lower().endswith(".exe") and _is_file(Path(configured)) else None
    try:
        native = shutil.which("codex.exe")
    except OSError:
        native = None
    if native and native.lower().endswith(".exe") and _is_file(Path(native)):
        return native
    # npm's launchers (codex.cmd / codex.ps1): the real binary sits in the package next to one of them
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        base = Path(entry.strip('"')) if entry.strip() else None
        if base is None or not any(_is_file(base / name) for name in ("codex.cmd", "codex.ps1", "codex")):
            continue
        for pattern in ("node_modules/@openai/codex*/vendor/*/bin/codex.exe",
                        "node_modules/@openai/codex/node_modules/@openai/codex*/vendor/*/bin/codex.exe"):
            try:
                vendored = sorted(p for p in base.glob(pattern) if _is_file(p))
            except OSError:
                continue  # an unreadable PATH entry: keep looking in the next one
            if vendored:
                return str(vendored[-1])
    return None


def _is_file(path: Path) -> bool:
    try:
        return path.is_file()
    except OSError:  # e.g. access denied on a PATH entry
        return False


def parse_features(stdout: str) -> set[str]:
    """`codex features list`: one feature per line, its name first."""
    return {line.split()[0] for line in stdout.splitlines() if line.strip() and not line.startswith(" ")}


class CodexCall(ClaudeCall):
    """Same cancel/timeout/process-tree handling as the Claude Code call."""

    def check_login(self, executable: str, timeout: float = 30) -> tuple[bool, str]:
        try:
            _code, stdout, stderr = self._run([executable, "login", "status"], "", timeout)
        except claude_client._Cancelled:
            return False, "cancelled"
        except claude_client._LaunchPending:
            return False, claude_client.LAUNCH_PENDING
        except claude_client._TimedOut:
            return False, "codex login status timed out"
        except OSError as exc:
            return False, f"codex unavailable: {type(exc).__name__}"
        text = (stdout + "\n" + stderr).strip()
        if CHATGPT_LOGIN in text:
            return True, ""
        return False, tr("不是 ChatGPT 订阅登录（{0}）", text.splitlines()[0] if text else tr("未登录"))

    def features(self, executable: str, timeout: float = 30) -> set[str] | None:
        """The feature names the installed CLI knows, or None when that cannot be read."""
        try:
            code, stdout, _err = self._run([executable, "features", "list"], "", timeout)
        except (claude_client._Cancelled, claude_client._LaunchPending, claude_client._TimedOut, OSError):
            return None
        known = parse_features(stdout) if code == 0 else set()
        return known or None

    def ask(self, executable: str, model: str, system: str, text: str, jpeg: bytes | None = None,
            effort: str = "low") -> ClaudeResult:
        known = self.features(executable)
        if self.cancelled:
            return ClaudeResult(False, error="cancelled", cancelled=True)
        if known is None:
            # Without the list the tools cannot be switched off: no screenshot is written, nothing is sent.
            return ClaudeResult(False, error=tr("读不到 Codex 的功能清单，无法确认能关闭它的工具，这次先不调用"))
        try:
            folder = _make_folder(Path(TEMP_ROOT or tempfile.gettempdir()))  # under the user's own %TEMP%
        except OSError as exc:
            return ClaudeResult(False, error=f"cannot prepare the screenshot folder: {exc}")
        try:
            reply_file = folder.path / "reply.txt"
            # forced_login_method: with an API-key login the CLI fails instead of billing the API.
            args = [executable, "exec", "--ephemeral", "--ignore-user-config", "--strict-config",
                    "-c", 'forced_login_method="chatgpt"', "-c", f'model_reasoning_effort="{effort}"',
                    "--skip-git-repo-check",
                    "-s", "read-only", "--color", "never", "-C", str(folder.path), "-o", str(reply_file)]
            for feature in RISKY_FEATURES:
                if feature in known:
                    args += ["--disable", feature]
            if model:
                args += ["-m", model]
            if jpeg:
                _write_new(folder, "screen.jpg", jpeg)  # a new file in the held folder, never an existing one
                args += ["-i", str(folder.path / "screen.jpg")]
            args.append("-")  # the prompt comes from stdin
            prompt = f"{system}\n\n----\n\n{text}\n\n{tr(INSTRUCTION) if jpeg else ''}"
            previous_cwd, self.cwd = self.cwd, str(folder.path)
            try:
                code, _stdout, stderr = self._run(args, prompt, self.timeout)
            finally:
                self.cwd = previous_cwd
            if code != 0:
                last = (stderr.strip().splitlines() or [f"exit code {code}"])[-1]
                return ClaudeResult(False, error=f"codex: {last[:200]}")
            data = _read(folder, "reply.txt")  # read inside the held folder, never through the path again
            reply = data.decode("utf-8", errors="replace").strip() if data else ""
            if not reply:
                return ClaudeResult(False, error=tr("codex 没有给出回答"))
            return ClaudeResult(True, text=reply)
        except claude_client._Cancelled:
            return ClaudeResult(False, error="cancelled", cancelled=True)
        except claude_client._LaunchPending:
            return ClaudeResult(False, error=claude_client.LAUNCH_PENDING)
        except claude_client._TimedOut:
            return ClaudeResult(False, error="timeout", timed_out=True)
        except OSError as exc:
            return ClaudeResult(False, error=f"cannot start codex: {exc}")
        finally:
            with _pending_lock:
                _pending[folder.path] = folder
            schedule_cleanup()  # deleted in the background: the answer never waits for file I/O


class _OnlyOthers(Exception):  # noqa: N818
    """Our files are gone, but another program left something of its own in the folder: it stays."""


class _NotOurs(Exception):  # noqa: N818 - not an OSError on purpose: never mistaken for "still locked"
    """A link, junction or file where a screenshot folder was expected."""


@dataclass(eq=False)
class _Folder:
    """A screenshot folder. On Windows it is held open from creation until it is deleted, so nobody can
    rename it or swap it for a link meanwhile, and everything inside is done relative to that handle."""
    path: Path
    handle: int | None = None

    def close(self) -> None:
        if self.handle is not None:
            _CloseHandle(self.handle)
            self.handle = None


@dataclass(frozen=True)
class _Recheck:
    """A leftover the start-up sweep could not open yet (another program had it open): checked again from
    scratch, relative to the temp root, before anything in it is deleted."""
    root: Path
    name: str
    cutoff: float
    root_id: tuple[int, int] | None = None  # (volume serial, file ID) of the temp root as it was scanned
    folder_id: tuple[int, int] | None = None  # ... and of the leftover folder itself


def _is_link(path: Path) -> bool:
    """A symbolic link, junction or other reparse point: never followed, never deleted through.
    A path that cannot even be inspected counts as unsafe too."""
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return False
    except OSError:
        return True
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)


if sys.platform == "win32":
    import ctypes
    import msvcrt
    from ctypes import wintypes

    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _nt = ctypes.WinDLL("ntdll")
    _CreateFileW = _k32.CreateFileW
    _CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                             wintypes.DWORD, wintypes.HANDLE]
    _CreateFileW.restype = wintypes.HANDLE
    _GetFileInformationByHandle = _k32.GetFileInformationByHandle

    class _ByHandleInfo(ctypes.Structure):
        _fields_ = [("dwFileAttributes", wintypes.DWORD), ("ftCreationTime", wintypes.FILETIME),
                    ("ftLastAccessTime", wintypes.FILETIME), ("ftLastWriteTime", wintypes.FILETIME),
                    ("dwVolumeSerialNumber", wintypes.DWORD), ("nFileSizeHigh", wintypes.DWORD),
                    ("nFileSizeLow", wintypes.DWORD), ("nNumberOfLinks", wintypes.DWORD),
                    ("nFileIndexHigh", wintypes.DWORD), ("nFileIndexLow", wintypes.DWORD)]

    class _UnicodeString(ctypes.Structure):
        _fields_ = [("Length", wintypes.USHORT), ("MaximumLength", wintypes.USHORT), ("Buffer", wintypes.LPWSTR)]

    class _ObjectAttributes(ctypes.Structure):
        _fields_ = [("Length", wintypes.ULONG), ("RootDirectory", wintypes.HANDLE),
                    ("ObjectName", ctypes.POINTER(_UnicodeString)), ("Attributes", wintypes.ULONG),
                    ("SecurityDescriptor", ctypes.c_void_p), ("SecurityQualityOfService", ctypes.c_void_p)]

    class _IoStatus(ctypes.Structure):
        _fields_ = [("Status", ctypes.c_void_p), ("Information", ctypes.c_size_t)]

    _GetFileInformationByHandle.argtypes = [wintypes.HANDLE, ctypes.POINTER(_ByHandleInfo)]
    _GetFileInformationByHandle.restype = wintypes.BOOL
    _SetFileInformationByHandle = _k32.SetFileInformationByHandle
    _SetFileInformationByHandle.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    _SetFileInformationByHandle.restype = wintypes.BOOL
    _NtCreateFile = _nt.NtCreateFile
    _NtCreateFile.argtypes = [ctypes.POINTER(wintypes.HANDLE), wintypes.ULONG, ctypes.POINTER(_ObjectAttributes),
                              ctypes.POINTER(_IoStatus), ctypes.c_void_p, wintypes.ULONG, wintypes.ULONG,
                              wintypes.ULONG, wintypes.ULONG, ctypes.c_void_p, wintypes.ULONG]
    _NtCreateFile.restype = ctypes.c_long
    _RtlNtStatusToDosError = _nt.RtlNtStatusToDosError
    _RtlNtStatusToDosError.argtypes = [ctypes.c_long]
    _RtlNtStatusToDosError.restype = wintypes.ULONG
    _GetFinalPathNameByHandleW = _k32.GetFinalPathNameByHandleW
    _GetFinalPathNameByHandleW.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD]
    _GetFinalPathNameByHandleW.restype = wintypes.DWORD
    _advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    _OpenProcessToken = _advapi.OpenProcessToken
    _OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    _OpenProcessToken.restype = wintypes.BOOL
    _GetTokenInformation = _advapi.GetTokenInformation
    _GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
                                     ctypes.POINTER(wintypes.DWORD)]
    _GetTokenInformation.restype = wintypes.BOOL
    _ConvertSidToStringSidW = _advapi.ConvertSidToStringSidW
    _ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
    _ConvertSidToStringSidW.restype = wintypes.BOOL
    _ConvertSddl = _advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW
    _ConvertSddl.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p),
                             ctypes.POINTER(wintypes.ULONG)]
    _ConvertSddl.restype = wintypes.BOOL
    _GetCurrentProcess = _k32.GetCurrentProcess
    _GetCurrentProcess.restype = wintypes.HANDLE
    _LocalFree = _k32.LocalFree
    _LocalFree.argtypes = [ctypes.c_void_p]
    _LocalFree.restype = ctypes.c_void_p
    _CloseHandle = _k32.CloseHandle
    _INVALID = wintypes.HANDLE(-1).value
    _DELETE, _SYNCHRONIZE, _GENERIC_READ, _GENERIC_WRITE = 0x10000, 0x100000, 0x80000000, 0x40000000
    _LIST, _ADD_FILE, _ADD_SUBDIRECTORY, _TRAVERSE, _READ_ATTRIBUTES = 0x1, 0x2, 0x4, 0x20, 0x80
    _HOLD = _DELETE | _LIST | _ADD_FILE | _TRAVERSE | _READ_ATTRIBUTES
    _SHARE_READ, _SHARE_READ_WRITE, _SHARE_ALL = 0x1, 0x3, 0x7  # no share-delete: no renaming meanwhile
    _OPEN_EXISTING = 3
    _BACKUP_SEMANTICS = 0x02000000  # needed to open a directory
    _OPEN_REPARSE_POINT = 0x00200000  # open a link itself, never what it points to
    _FILE_OPEN, _FILE_CREATE = 1, 2
    _DIRECTORY_FILE, _SYNCHRONOUS, _NON_DIRECTORY_FILE = 0x1, 0x20, 0x40
    _OBJ_CASE_INSENSITIVE = 0x40
    _FILE_DISPOSITION_INFO = 4

    def _check(handle) -> int:
        if handle in (None, 0, _INVALID):
            raise ctypes.WinError(ctypes.get_last_error())  # FileNotFoundError when it is not there
        return handle

    def _info(handle: int) -> _ByHandleInfo:
        info = _ByHandleInfo()
        if not _GetFileInformationByHandle(handle, ctypes.byref(info)):
            raise ctypes.WinError(ctypes.get_last_error())
        return info

    def _attributes(handle: int) -> int:
        return _info(handle).dwFileAttributes

    def _created(info: _ByHandleInfo) -> float:
        ticks = info.ftCreationTime.dwHighDateTime << 32 | info.ftCreationTime.dwLowDateTime
        return ticks / 10_000_000 - 11_644_473_600  # FILETIME (1601, 100 ns) to Unix seconds

    def _real_path(handle: int) -> Path:
        """Where the held folder really is, every junction and link on the way resolved. While the folder
        is held, none of these real parent folders can be renamed, so this path cannot be redirected."""
        buffer = ctypes.create_unicode_buffer(32768)
        size = _GetFinalPathNameByHandleW(handle, buffer, len(buffer), 0)
        if not size or size >= len(buffer):
            raise ctypes.WinError(ctypes.get_last_error())
        text = buffer.value
        if text.startswith("\\\\?\\UNC\\"):
            text = "\\\\" + text[8:]
        elif text.startswith("\\\\?\\"):
            text = text[4:]
        return Path(text)

    _user_sid: str | None = None

    def _current_user_sid() -> str:
        global _user_sid
        if _user_sid is None:
            token = wintypes.HANDLE()
            if not _OpenProcessToken(_GetCurrentProcess(), 0x8, ctypes.byref(token)):  # TOKEN_QUERY
                raise ctypes.WinError(ctypes.get_last_error())
            try:
                size = wintypes.DWORD()
                _GetTokenInformation(token, 1, None, 0, ctypes.byref(size))  # TokenUser: first ask the size
                buffer = ctypes.create_string_buffer(size.value)
                if not _GetTokenInformation(token, 1, buffer, size, ctypes.byref(size)):
                    raise ctypes.WinError(ctypes.get_last_error())
                sid = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_void_p))[0]
                text = wintypes.LPWSTR()
                if not _ConvertSidToStringSidW(sid, ctypes.byref(text)):
                    raise ctypes.WinError(ctypes.get_last_error())
                _user_sid = text.value
                _LocalFree(text)
            finally:
                _CloseHandle(token)
        return _user_sid

    def _private_descriptor() -> ctypes.c_void_p:
        """Only this user and the system, not inherited from %TEMP% (which may be shared): P = protected."""
        descriptor = ctypes.c_void_p()
        sddl = f"D:P(A;OICI;FA;;;{_current_user_sid()})(A;OICI;FA;;;SY)"
        if not _ConvertSddl(sddl, 1, ctypes.byref(descriptor), None):
            raise ctypes.WinError(ctypes.get_last_error())
        return descriptor

    def _open_in(directory: int, name: str, access: int, share: int, disposition: int, options: int,
                 security: int | None = None) -> int:
        """Open `name` inside the folder that `directory` holds: no path above it is looked at again,
        so a link swapped in anywhere above can never send this somewhere else."""
        text = ctypes.create_unicode_buffer(name)
        unicode = _UnicodeString(len(name) * 2, len(name) * 2, ctypes.cast(text, wintypes.LPWSTR))
        attributes = _ObjectAttributes(ctypes.sizeof(_ObjectAttributes), directory, ctypes.pointer(unicode),
                                       _OBJ_CASE_INSENSITIVE, security, None)
        handle, io = wintypes.HANDLE(), _IoStatus()
        status = _NtCreateFile(ctypes.byref(handle), access | _SYNCHRONIZE, ctypes.byref(attributes),
                               ctypes.byref(io), None, 0, share, disposition, options | _SYNCHRONOUS, None, 0)
        if status < 0:
            raise ctypes.WinError(_RtlNtStatusToDosError(status))
        return handle.value

    def _delete_by_handle(handle: int) -> None:
        """Delete exactly the opened object, whatever its path leads to by now (a folder only when empty)."""
        flag = ctypes.c_ubyte(1)
        if not _SetFileInformationByHandle(handle, _FILE_DISPOSITION_INFO, ctypes.byref(flag), 1):
            raise ctypes.WinError(ctypes.get_last_error())

    def _make_folder(root: Path) -> _Folder:
        """A new folder, created and held through one handle: there is no moment it could be swapped."""
        descriptor = _private_descriptor()
        parent = None
        try:
            parent = _check(_CreateFileW(str(root), _ADD_SUBDIRECTORY | _TRAVERSE, _SHARE_ALL, None, _OPEN_EXISTING,
                                         _BACKUP_SEMANTICS, None))
            for _attempt in range(10):
                name = FOLDER_PREFIX + secrets.token_hex(8)
                try:
                    handle = _open_in(parent, name, _HOLD, _SHARE_READ_WRITE, _FILE_CREATE, _DIRECTORY_FILE,
                                      descriptor.value)
                except FileExistsError:
                    continue
                folder = _Folder(root / name, handle)
                try:
                    folder.path = _real_path(handle)  # what the CLI is given: no link left to swap
                except OSError:
                    _delete_by_handle(handle)
                    folder.close()
                    raise
                return folder
            raise FileExistsError("no free name for the screenshot folder")
        finally:
            if parent is not None:
                _CloseHandle(parent)
            _LocalFree(descriptor)

    def _leftovers(root: Path, cutoff: float) -> list[_Folder]:
        """Folders an earlier run left in `root`: each opened relative to the held root and checked through
        its own handle (plain folder, made before this run), so nothing above can be swapped in between."""
        parent = _hold_root(root)
        found = []
        try:
            root_id = _identity_of(_info(parent))
            for name in os.listdir(root):
                if not name.startswith(FOLDER_PREFIX) or _is_link(root / name):
                    continue  # a link (or something not even inspectable) is not ours to clean
                try:
                    folder = _open_leftover(parent, root, name, cutoff)
                except FileNotFoundError:
                    continue
                except OSError:  # another program has it open right now: the background cleanup checks again
                    folder_id = _peek_leftover(parent, name, cutoff)
                    if folder_id is not None:  # without knowing which folder it is, nothing is deleted by name
                        with _pending_lock:  # never replaces a folder a call already holds there
                            _pending.setdefault(root / name, _Recheck(root, name, cutoff, root_id, folder_id))
                    continue
                if folder is not None:
                    found.append(folder)
        finally:
            _CloseHandle(parent)
        return found

    def _identity_of(info: _ByHandleInfo) -> tuple[int, int]:
        return info.dwVolumeSerialNumber, info.nFileIndexHigh << 32 | info.nFileIndexLow

    def _hold_root(root: Path) -> int:
        return _check(_CreateFileW(str(root), _LIST | _TRAVERSE | _READ_ATTRIBUTES, _SHARE_READ_WRITE, None,
                                   _OPEN_EXISTING, _BACKUP_SEMANTICS, None))

    def _open_leftover(parent: int, root: Path, name: str, cutoff: float,
                       expected: tuple[int, int] | None = None) -> _Folder | None:
        """Open `name` relative to the held root and check it through its own handle: a plain folder made
        before this run (and, when given, the very folder seen before) is returned held; anything else is
        closed again and None returned."""
        handle = _open_in(parent, name, _HOLD, _SHARE_READ_WRITE, _FILE_OPEN, _DIRECTORY_FILE | _OPEN_REPARSE_POINT)
        try:
            info = _info(handle)
        except BaseException:
            _CloseHandle(handle)
            raise
        if (info.dwFileAttributes & stat.FILE_ATTRIBUTE_REPARSE_POINT or _created(info) >= cutoff
                or (expected is not None and _identity_of(info) != expected)):
            _CloseHandle(handle)
            return None
        return _Folder(root / name, handle)

    def _peek_leftover(parent: int, name: str, cutoff: float) -> tuple[int, int] | None:
        """Which folder a busy leftover is: an attributes-only handle is not blocked by the other program."""
        try:
            handle = _open_in(parent, name, _READ_ATTRIBUTES, _SHARE_ALL, _FILE_OPEN,
                              _DIRECTORY_FILE | _OPEN_REPARSE_POINT)
        except OSError:
            return None
        try:
            info = _info(handle)
        except OSError:
            return None
        finally:
            _CloseHandle(handle)
        if info.dwFileAttributes & stat.FILE_ATTRIBUTE_REPARSE_POINT or _created(info) >= cutoff:
            return None
        return _identity_of(info)

    def _reopen(item: _Recheck) -> _Folder | None:
        parent = _hold_root(item.root)
        try:
            if item.root_id is not None and _identity_of(_info(parent)) != item.root_id:
                raise _NotOurs(item.root)  # the temp path now leads to another folder: not ours to clean
            return _open_leftover(parent, item.root, item.name, item.cutoff, item.folder_id)
        finally:
            _CloseHandle(parent)

    def _hold(path: Path) -> _Folder:
        """Hold an existing folder (one left by an earlier run); a link or file there is not ours."""
        handle = _check(_CreateFileW(str(path), _HOLD, _SHARE_READ_WRITE, None, _OPEN_EXISTING,
                                     _BACKUP_SEMANTICS | _OPEN_REPARSE_POINT, None))
        try:
            attributes = _attributes(handle)
        except OSError:
            _CloseHandle(handle)
            raise
        if attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT or not attributes & stat.FILE_ATTRIBUTE_DIRECTORY:
            _CloseHandle(handle)
            raise _NotOurs(path)
        return _Folder(path, handle)

    def _write_new(folder: _Folder, name: str, data: bytes) -> None:
        """Always a brand-new file: an existing one (say, a hard link to something else) is never written."""
        handle = _open_in(folder.handle, name, _GENERIC_WRITE, _SHARE_READ, _FILE_CREATE, _NON_DIRECTORY_FILE)
        with _as_file(handle, os.O_WRONLY, "wb") as file:
            file.write(data)

    def _read(folder: _Folder, name: str) -> bytes | None:
        try:
            handle = _open_in(folder.handle, name, _GENERIC_READ | _READ_ATTRIBUTES, _SHARE_READ_WRITE, _FILE_OPEN,
                              _NON_DIRECTORY_FILE | _OPEN_REPARSE_POINT)
        except FileNotFoundError:
            return None
        try:
            link = _attributes(handle) & stat.FILE_ATTRIBUTE_REPARSE_POINT
        except BaseException:
            _CloseHandle(handle)  # never left open: it would block deleting the reply later
            raise
        if link:
            _CloseHandle(handle)
            return None
        with _as_file(handle, os.O_RDONLY, "rb") as file:
            return file.read()

    def _as_file(handle: int, flags: int, mode: str):
        """A Python file that owns the handle from here on; on any failure before that, the handle is closed."""
        try:
            descriptor = msvcrt.open_osfhandle(handle, flags)
        except BaseException:
            _CloseHandle(handle)
            raise
        try:
            return os.fdopen(descriptor, mode)
        except BaseException:
            os.close(descriptor)  # closes the handle too
            raise

    def _delete(folder: _Folder) -> bool:
        """Remove only what a call writes (OUR_FILES), each through its own handle opened inside the held
        folder, then the folder itself; anything else is left alone. Unlinked, never overwritten: a hard
        link can never empty a file elsewhere."""
        try:
            for name in OUR_FILES:
                try:
                    handle = _open_in(folder.handle, name, _DELETE | _READ_ATTRIBUTES, _SHARE_ALL, _FILE_OPEN,
                                      _NON_DIRECTORY_FILE | _OPEN_REPARSE_POINT)
                except FileNotFoundError:
                    continue
                try:
                    if not _attributes(handle) & stat.FILE_ATTRIBUTE_REPARSE_POINT:  # a link there is not ours
                        _delete_by_handle(handle)  # fails while the CLI still holds the file: retried later
                finally:
                    _CloseHandle(handle)
            _delete_by_handle(folder.handle)  # fails while anything else is still inside
        except OSError:
            if not any(_still_there(folder, name) for name in OUR_FILES) and _has_others(folder):
                raise _OnlyOthers(folder.path) from None
            return False
        folder.close()  # the folder goes away with the last handle
        return True

    def _still_there(folder: _Folder, name: str) -> bool:
        try:
            handle = _open_in(folder.handle, name, _READ_ATTRIBUTES, _SHARE_ALL, _FILE_OPEN, _OPEN_REPARSE_POINT)
        except FileNotFoundError:
            return False
        except OSError:
            return True  # e.g. deletion still pending while the CLI holds it: ours, busy
        _CloseHandle(handle)
        return True
else:
    def _CloseHandle(_handle) -> None:  # noqa: N802 - no handles here
        pass

    def _make_folder(root: Path) -> _Folder:
        return _Folder(Path(tempfile.mkdtemp(prefix=FOLDER_PREFIX, dir=root)))

    def _hold(path: Path) -> _Folder:
        if _is_link(path) or not path.is_dir():
            raise _NotOurs(path)
        return _Folder(path)

    def _write_new(folder: _Folder, name: str, data: bytes) -> None:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        with os.fdopen(os.open(folder.path / name, flags, 0o600), "wb") as file:
            file.write(data)

    def _leftovers(root: Path, cutoff: float) -> list[_Folder]:
        found = []
        for path in root.glob(FOLDER_PREFIX + "*"):
            try:
                if _is_link(path) or not path.is_dir():
                    continue
                info = os.lstat(path)
                if getattr(info, "st_birthtime", info.st_ctime) < cutoff:
                    found.append(_Folder(path))
            except OSError:
                continue
        return found

    def _reopen(item: _Recheck) -> _Folder | None:
        found = [f for f in _leftovers(item.root, item.cutoff) if f.path.name == item.name]
        return found[0] if found else None

    def _read(folder: _Folder, name: str) -> bytes | None:
        item = folder.path / name
        if _is_link(item) or not item.is_file():
            return None
        return item.read_bytes()

    def _delete(folder: _Folder) -> bool:
        try:
            for name in OUR_FILES:
                item = folder.path / name
                if _is_link(item):
                    continue
                try:
                    item.unlink()
                except FileNotFoundError:
                    pass
            folder.path.rmdir()  # only succeeds when nothing else is inside
        except OSError:
            if not any(_is_link(folder.path / n) or (folder.path / n).exists() for n in OUR_FILES) \
                    and _has_others(folder):
                raise _OnlyOthers(folder.path) from None
            return False
        return True


def _has_others(folder: _Folder) -> bool:
    try:
        return any(name not in OUR_FILES for name in os.listdir(folder.path))
    except OSError:
        return False  # cannot tell: treated as busy and retried


def remove_folder(target: Path | _Folder, waits: tuple[float, ...] = (0,)) -> bool:
    """The screenshot must not outlive the call: if the CLI still holds the file, keep the folder (still
    held) on a list that the background cleanup retries every second and when the pet quits."""
    if isinstance(target, _Folder):
        folder = target
    else:
        try:
            folder = _hold(target)
        except FileNotFoundError:
            with _pending_lock:
                _pending.pop(target, None)
            return True
        except _NotOurs:
            with _pending_lock:
                _pending.pop(target, None)
            log.warning("%s is not a plain screenshot folder; leaving it alone", target)
            return False
        except OSError:  # in use or not inspectable right now
            with _pending_lock:
                _pending[target] = None
            return False
    for wait in waits:
        time.sleep(wait)
        try:
            done = _delete(folder)
        except _OnlyOthers:
            folder.close()  # let go: the folder is not ours alone any more
            with _pending_lock:
                _pending.pop(folder.path, None)
            log.warning("%s also holds files that are not ours; the screenshot is gone, the rest stays", folder.path)
            return False
        if done:
            with _pending_lock:
                _pending.pop(folder.path, None)
            return True
    with _pending_lock:
        _pending[folder.path] = folder
    log.warning("could not delete the temporary screenshot folder %s yet; will retry", folder.path)
    return False


def has_pending() -> bool:
    with _pending_lock:
        return bool(_pending)


def retry_pending() -> int:
    """Try the folders that could not be deleted earlier; returns how many are still left."""
    with _pending_lock:
        folders = list(_pending.items())
    for path, held in folders:
        if isinstance(held, _Recheck):
            try:
                folder = _reopen(held)
            except (FileNotFoundError, _NotOurs):
                folder = None
            except OSError:
                continue  # still in use: next time
            if folder is None:  # gone, or not a plain leftover of an earlier run after all
                with _pending_lock:
                    _pending.pop(path, None)
                continue
            remove_folder(folder)
        else:
            remove_folder(held or path)
    with _pending_lock:
        return len(_pending)


def schedule_cleanup(sweep: bool = False) -> None:
    """All screenshot cleanup runs on one background thread: file I/O can hang (e.g. on a network share),
    so neither a call nor the UI ever waits for it."""
    global _worker, _wanted
    with _worker_lock:
        if sweep:
            _sweeps.append(TEMP_ROOT)  # fixed now: the worker never reads a value changed later
        _wanted = True
        if _worker is None:
            _worker = threading.Thread(target=_work, name="codex-cleanup", daemon=True)
            _worker.start()


def _work() -> None:
    global _worker, _wanted
    while True:
        with _worker_lock:
            if not _wanted:
                _worker = None  # cleared under the lock, so a request made now starts a new worker
                return
            _wanted = False
            sweeps = list(_sweeps)
            _sweeps.clear()
        try:
            for root in sweeps:
                if sweep_stale(root):
                    log.warning("some temporary Codex screenshot folders could not be removed yet")
            retry_pending()
        except Exception:  # noqa: BLE001 - the worker must survive to clean up later
            log.exception("Codex screenshot cleanup failed")


def cleanup_running() -> bool:
    with _worker_lock:
        return _worker is not None


def wait_cleanup(timeout: float) -> None:
    with _worker_lock:
        worker = _worker
    if worker is not None:
        worker.join(timeout)


def sweep_stale(temp_dir: Path | None = None, born_before: float | None = None) -> int:
    """At start-up: remove screenshot folders a crash or power loss left behind. Returns how many remain.
    Folders made by this run are skipped, so a call that started meanwhile keeps its own."""
    cutoff = _STARTED if born_before is None else born_before
    left = 0
    try:
        root = Path(temp_dir or TEMP_ROOT or tempfile.gettempdir())  # gettempdir() raises when no temp dir is usable
        candidates = _leftovers(root, cutoff)
    except OSError as exc:
        log.warning("cannot look for leftover Codex screenshot folders: %s", exc)
        return 0
    for folder in candidates:
        try:
            if not remove_folder(folder):
                left += 1
        except OSError:  # never let a strange leftover stop the pet from starting
            left += 1
    return left
