"""Start with Windows: a shortcut in the user's Startup folder (the same one Task Manager lists).

Only a shortcut that points at this program is ever removed. If the user disabled the entry in
Task Manager (Startup apps), it counts as off; turning it on again clears that flag.
"""
from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

SHORTCUT_NAME = "Desk Sister.lnk"
LEGACY_NAMES = ("Claude 桌宠.lnk",)  # older versions; adopted when they point at this program
_APPROVED_KEY = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\StartupFolder"
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

# Paths go in through environment variables, never spliced into the script text.
_CREATE = r"""
$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:PET_LNK)
$s.TargetPath = $env:PET_TARGET
$s.Arguments = $env:PET_ARGS
$s.WorkingDirectory = $env:PET_WORKDIR
if ($env:PET_ICON) { $s.IconLocation = "$($env:PET_ICON),0" }
$s.Description = 'Desk Sister'
$s.Save()
"""
_READ = r"""
$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:PET_LNK)
[Console]::OutputEncoding = [Text.Encoding]::UTF8
Write-Output $s.TargetPath
Write-Output $s.WorkingDirectory
Write-Output $s.Arguments
"""


@dataclass(frozen=True)
class Launch:
    target: str
    arguments: str
    workdir: str
    icon: str = ""


def startup_dir() -> Path:
    return Path(os.environ.get("APPDATA", str(Path.home()))) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def current_launch(app_file: Path, icon: Path | None = None) -> Launch:
    """How this running copy was started: pythonw + app.py, or the frozen exe."""
    icon_text = str(icon) if icon and icon.is_file() else ""
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable)
        return Launch(str(exe), "", str(exe.parent), icon_text)
    exe = Path(sys.executable)
    windowed = exe.with_name("pythonw.exe")
    target = windowed if windowed.is_file() else exe
    return Launch(str(target), f'"{app_file}"', str(app_file.parent), icon_text)


def _powershell(script: str, env: dict[str, str], timeout: float = 30) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
        env={**os.environ, **env}, creationflags=_NO_WINDOW,
    )


def read_shortcut(lnk: Path) -> tuple[str, str, str] | None:
    """(target, working directory, arguments) of a .lnk file, or None if it cannot be read."""
    if not lnk.is_file():
        return None
    proc = _powershell(_READ, {"PET_LNK": str(lnk)})
    lines = proc.stdout.splitlines()
    if proc.returncode != 0 or not lines:
        return None
    lines += ["", ""]
    return lines[0].strip(), lines[1].strip(), lines[2].strip()


def _same_path(a: str, b: str) -> bool:
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def points_to_us(lnk: Path, launch: Launch) -> bool:
    found = read_shortcut(lnk)
    if found is None:
        return False
    target, workdir, arguments = found
    if not _same_path(target, launch.target):
        # The same venv may be started via python.exe or pythonw.exe; both are this program.
        # Only then: a frozen exe (or any other target) must match exactly.
        interpreters = ("python.exe", "pythonw.exe")
        same_venv = _same_path(str(Path(target).parent), str(Path(launch.target).parent))
        if not (same_venv and Path(target).name.lower() in interpreters and Path(launch.target).name.lower() in interpreters):
            return False
    if not launch.arguments:
        return not arguments
    script = arguments.strip('"')
    if script and not os.path.isabs(script):
        script = os.path.join(workdir, script)  # relative to the shortcut's own "Start in"
    return bool(script) and _same_path(script, launch.arguments.strip('"'))


def disabled_in_task_manager(name: str = SHORTCUT_NAME) -> bool:
    if sys.platform != "win32":
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _APPROVED_KEY) as key:
            data, _kind = winreg.QueryValueEx(key, name)
    except OSError:
        return False
    return flag_means_disabled(data)


def flag_means_disabled(data: bytes) -> bool:
    """StartupApproved first byte: even (0x02/0x06) = enabled, odd (0x03/0x07) = disabled by the user."""
    return isinstance(data, (bytes, bytearray)) and len(data) > 0 and bool(data[0] & 1)


def clear_task_manager_flag(name: str = SHORTCUT_NAME) -> None:
    if sys.platform != "win32":
        return
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _APPROVED_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, name)
    except FileNotFoundError:
        pass  # no flag (or no key): nothing was disabled
    # Any other error (e.g. access denied) propagates: the entry would stay disabled, so it is not a success.


class AutostartError(Exception):
    pass


ON, OFF, FOREIGN = "on", "off", "foreign"


class Autostart:
    def __init__(self, launch: Launch, folder: Path | None = None, task_manager: bool = True) -> None:
        self.launch = launch
        self.folder = folder or startup_dir()
        self.task_manager = task_manager  # tests use a temp folder and leave the real registry alone

    @property
    def shortcut(self) -> Path:
        return self.folder / SHORTCUT_NAME

    def _legacy_ours(self) -> list[Path]:
        return [lnk for lnk in (self.folder / name for name in LEGACY_NAMES)
                if lnk.exists() and points_to_us(lnk, self.launch)]

    def state(self) -> str:
        """ON, OFF or FOREIGN (a same-named shortcut of another program). Slow (PowerShell): not on the UI thread.

        ON whenever any startup shortcut to this program (also an older version's name) is not disabled:
        that one alone would start it with Windows.
        """
        exists = self.shortcut.exists()
        mine = exists and points_to_us(self.shortcut, self.launch)
        ours = ([self.shortcut] if mine else []) + self._legacy_ours()
        if any(not (self.task_manager and disabled_in_task_manager(lnk.name)) for lnk in ours):
            return ON
        if exists and not mine:
            return FOREIGN
        return OFF

    def _remove_legacy(self) -> None:
        for legacy in self._legacy_ours():
            try:
                legacy.unlink()
            except OSError as exc:
                raise AutostartError(f"删不掉旧的启动快捷方式 {legacy.name}：{exc}") from exc

    def is_enabled(self) -> bool:
        return self.state() == ON

    def enable(self) -> None:
        if self.shortcut.exists() and not points_to_us(self.shortcut, self.launch):
            raise AutostartError(f"{self.shortcut.name} 已存在且指向其他程序，未覆盖")
        self.folder.mkdir(parents=True, exist_ok=True)
        proc = _powershell(_CREATE, {
            "PET_LNK": str(self.shortcut), "PET_TARGET": self.launch.target, "PET_ARGS": self.launch.arguments,
            "PET_WORKDIR": self.launch.workdir, "PET_ICON": self.launch.icon,
        })
        if proc.returncode != 0 or not self.shortcut.is_file():
            raise AutostartError("创建启动快捷方式失败：" + (proc.stderr.strip().splitlines() or ["未知错误"])[-1])
        if self.task_manager:
            try:
                clear_task_manager_flag()
            except OSError as exc:
                raise AutostartError(f"无法解除任务管理器中的禁用：{exc}") from exc
        self._remove_legacy()  # one entry under the new name, never two

    def disable(self) -> None:
        self._remove_legacy()
        if not self.shortcut.exists():
            return
        if not points_to_us(self.shortcut, self.launch):
            raise AutostartError(f"{self.shortcut.name} 指向其他程序，未删除")
        self.shortcut.unlink()
