"""Foreground-window lookup, screenshots, privacy filter and change detection."""
from __future__ import annotations

import fnmatch
import io
import os
import sys
from dataclasses import dataclass

from PIL import Image, ImageChops, ImageStat


@dataclass(frozen=True)
class WindowInfo:
    hwnd: int
    title: str
    process_name: str
    pid: int
    rect: tuple[int, int, int, int]  # left, top, right, bottom in physical pixels
    minimized: bool = False


def is_blocked(title: str, process_name: str, blocklist: list[str]) -> bool:
    haystack = f"{title}\n{process_name}".casefold()
    return any(word.casefold() in haystack for word in blocklist if word)


def literal_rule(process_name: str) -> str:
    """An allowlist rule matching exactly this program name: [, * and ? are escaped (Editor[1].exe)."""
    return "".join(f"[{c}]" if c in "[*?" else c for c in process_name)


def matches_allowlist(rules: list[str], process_name: str, title: str) -> bool:
    """Allowlist rules, case-insensitive with * and ? wildcards (idea from dsh-pet-indesktop).

    A plain rule matches the process name only; matching the window title needs an explicit
    "title:" prefix, because titles can carry document names and other private text.
    """
    process = (process_name or "").strip().casefold()
    window_title = (title or "").strip().casefold()
    for rule in rules or []:
        if not isinstance(rule, str) or not rule.strip():
            continue
        pattern = rule.strip().casefold()
        if pattern.startswith("title:"):
            pattern = pattern[len("title:"):].strip()
            if pattern and window_title and fnmatch.fnmatchcase(window_title, pattern):
                return True
        elif process and fnmatch.fnmatchcase(process, pattern):
            return True
    return False


def to_jpeg(image: Image.Image, max_side: int = 1280, quality: int = 70) -> bytes:
    image = image.convert("RGB")
    image.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=quality, optimize=True)
    return buffer.getvalue()


def fingerprint(image: Image.Image) -> Image.Image:
    return image.convert("L").resize((64, 40), Image.Resampling.BILINEAR)


def change_ratio(a: Image.Image | None, b: Image.Image | None) -> float:
    """0.0 = identical fingerprints, 1.0 = completely different."""
    if a is None or b is None:
        return 1.0
    diff = ImageChops.difference(a, b)
    return ImageStat.Stat(diff).mean[0] / 255.0


# SHQueryUserNotificationState values meaning "do not disturb the user now":
# QUNS_BUSY (a full-screen app), QUNS_RUNNING_D3D_FULL_SCREEN, QUNS_PRESENTATION_MODE.
QUIET_NOTIFICATION_STATES = frozenset({2, 3, 4})
# The desktop and taskbar cover the screen too, but are not "an app in full screen".
SHELL_WINDOW_CLASSES = frozenset({"Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd"})


def covers_monitor(rect: tuple[int, int, int, int], monitor: tuple[int, int, int, int]) -> bool:
    left, top, right, bottom = rect
    m_left, m_top, m_right, m_bottom = monitor
    return left <= m_left and top <= m_top and right >= m_right and bottom >= m_bottom


def idle_from_ticks(now_ms: int, last_input_ms: int) -> float:
    """Seconds since the last input; both tick counts are 32-bit and wrap after ~49.7 days."""
    return ((now_ms - last_input_ms) & 0xFFFFFFFF) / 1000.0


def is_blank(image: Image.Image) -> bool:
    """PrintWindow returns an all-black bitmap for windows it cannot render."""
    return image.convert("L").point(lambda v: 255 if v > 8 else 0).getbbox() is None


if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    _dwmapi = ctypes.WinDLL("dwmapi")
    _HANDLE = ctypes.c_void_p  # handles are pointer-sized; the c_int default would truncate them
    _user32.GetForegroundWindow.restype = wintypes.HWND
    _user32.IsWindow.argtypes = [wintypes.HWND]
    _user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    _user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    _user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    _user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    _user32.IsIconic.argtypes = [wintypes.HWND]
    _user32.GetDC.argtypes = [wintypes.HWND]
    _user32.GetDC.restype = _HANDLE
    _user32.ReleaseDC.argtypes = [wintypes.HWND, _HANDLE]
    _user32.PrintWindow.argtypes = [wintypes.HWND, _HANDLE, wintypes.UINT]
    _user32.PrintWindow.restype = wintypes.BOOL
    _gdi32.CreateCompatibleDC.argtypes = [_HANDLE]
    _gdi32.CreateCompatibleDC.restype = _HANDLE
    _gdi32.CreateCompatibleBitmap.argtypes = [_HANDLE, ctypes.c_int, ctypes.c_int]
    _gdi32.CreateCompatibleBitmap.restype = _HANDLE
    _gdi32.SelectObject.argtypes = [_HANDLE, _HANDLE]
    _gdi32.SelectObject.restype = _HANDLE
    _gdi32.DeleteObject.argtypes = [_HANDLE]
    _gdi32.DeleteDC.argtypes = [_HANDLE]
    _kernel32.OpenProcess.restype = wintypes.HANDLE
    _kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _dwmapi.DwmGetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.POINTER(wintypes.RECT), wintypes.DWORD]
    _PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    _DWMWA_EXTENDED_FRAME_BOUNDS = 9
    _PW_RENDERFULLCONTENT = 0x2
    _user32.SetThreadDpiAwarenessContext.argtypes = [_HANDLE]
    _user32.SetThreadDpiAwarenessContext.restype = _HANDLE
    _PER_MONITOR_AWARE_V2 = _HANDLE(-4)

    def _physical_pixels(func):
        """Run with per-monitor DPI awareness so every Win32 rect is in the same physical pixels."""
        def wrapper(*args, **kwargs):
            previous = _user32.SetThreadDpiAwarenessContext(_PER_MONITOR_AWARE_V2)
            try:
                return func(*args, **kwargs)
            finally:
                if previous:
                    _user32.SetThreadDpiAwarenessContext(previous)
        return wrapper

    class _BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
            ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
            ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG), ("biYPelsPerMeter", wintypes.LONG),
            ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD),
        ]

    _gdi32.GetDIBits.argtypes = [_HANDLE, _HANDLE, wintypes.UINT, wintypes.UINT, ctypes.c_void_p,
                                 ctypes.POINTER(_BITMAPINFOHEADER), wintypes.UINT]

    def _process_name(pid: int) -> str:
        """Empty string means the process could not be identified; callers must treat that as unsafe."""
        handle = _kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return ""
        try:
            size = wintypes.DWORD(32768)  # maximum extended-length path
            buffer = ctypes.create_unicode_buffer(size.value)
            if _kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                return os.path.basename(buffer.value)
            return ""
        finally:
            _kernel32.CloseHandle(handle)

    def foreground_window() -> WindowInfo | None:
        hwnd = _user32.GetForegroundWindow()
        return window_info(int(hwnd)) if hwnd else None

    @_physical_pixels
    def window_info(hwnd: int) -> WindowInfo | None:
        if not hwnd or not _user32.IsWindow(hwnd):
            return None
        length = _user32.GetWindowTextLengthW(hwnd)
        buffer = ctypes.create_unicode_buffer(length + 1)
        _user32.GetWindowTextW(hwnd, buffer, length + 1)
        pid = wintypes.DWORD()
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        rect = wintypes.RECT()
        # The extended frame excludes the invisible resize borders that GetWindowRect includes.
        if _dwmapi.DwmGetWindowAttribute(hwnd, _DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(rect), ctypes.sizeof(rect)) != 0:
            _user32.GetWindowRect(hwnd, ctypes.byref(rect))
        return WindowInfo(
            hwnd=int(hwnd), title=buffer.value, process_name=_process_name(pid.value), pid=pid.value,
            rect=(rect.left, rect.top, rect.right, rect.bottom), minimized=bool(_user32.IsIconic(hwnd)),
        )

    class _LastInputInfo(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

    class _MonitorInfo(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                    ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

    _user32.GetLastInputInfo.argtypes = [ctypes.POINTER(_LastInputInfo)]
    _user32.GetLastInputInfo.restype = wintypes.BOOL
    _kernel32.GetTickCount.restype = wintypes.DWORD
    _user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
    _user32.MonitorFromWindow.restype = _HANDLE
    _user32.GetMonitorInfoW.argtypes = [_HANDLE, ctypes.POINTER(_MonitorInfo)]
    _user32.GetMonitorInfoW.restype = wintypes.BOOL
    _user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    _shell32 = ctypes.WinDLL("shell32")
    _shell32.SHQueryUserNotificationState.argtypes = [ctypes.POINTER(ctypes.c_int)]
    _MONITOR_DEFAULTTONEAREST = 2

    def idle_seconds() -> float | None:
        """Seconds since the last keyboard/mouse input in this session, or None if unknown."""
        info = _LastInputInfo(cbSize=ctypes.sizeof(_LastInputInfo))
        if not _user32.GetLastInputInfo(ctypes.byref(info)):
            return None
        return idle_from_ticks(_kernel32.GetTickCount(), info.dwTime)

    def notification_busy() -> bool:
        """Windows' own verdict: a full-screen app, D3D game or presentation is running."""
        state = ctypes.c_int(0)
        if _shell32.SHQueryUserNotificationState(ctypes.byref(state)) != 0:
            return False
        return state.value in QUIET_NOTIFICATION_STATES

    @_physical_pixels
    def is_fullscreen(info: WindowInfo | None) -> bool:
        """The window fills its whole monitor (borderless games, F11 browsers, video players)."""
        if info is None or info.minimized or not info.hwnd:
            return False
        name = ctypes.create_unicode_buffer(256)
        _user32.GetClassNameW(info.hwnd, name, 256)
        if name.value in SHELL_WINDOW_CLASSES:
            return False
        monitor = _user32.MonitorFromWindow(info.hwnd, _MONITOR_DEFAULTTONEAREST)
        details = _MonitorInfo(cbSize=ctypes.sizeof(_MonitorInfo))
        if not monitor or not _user32.GetMonitorInfoW(monitor, ctypes.byref(details)):
            return False
        r = details.rcMonitor
        return covers_monitor(info.rect, (r.left, r.top, r.right, r.bottom))

    @_physical_pixels
    def capture_window(info: WindowInfo) -> Image.Image | None:
        """Render only this window's own content (PrintWindow), never whatever overlaps it on screen."""
        outer = wintypes.RECT()
        if not _user32.GetWindowRect(info.hwnd, ctypes.byref(outer)):
            return None
        width, height = outer.right - outer.left, outer.bottom - outer.top
        if width < 50 or height < 50 or width * height > 64_000_000:
            return None
        screen_dc = _user32.GetDC(None)
        mem_dc = _gdi32.CreateCompatibleDC(screen_dc) if screen_dc else None
        bitmap = _gdi32.CreateCompatibleBitmap(screen_dc, width, height) if mem_dc else None
        previous = _gdi32.SelectObject(mem_dc, bitmap) if bitmap else None
        try:
            if not previous:
                return None
            printed = _user32.PrintWindow(info.hwnd, mem_dc, _PW_RENDERFULLCONTENT)
            # GetDIBits requires that the bitmap is not selected into any DC, so restore first.
            _gdi32.SelectObject(mem_dc, previous)
            previous = None
            if not printed:
                return None
            header = _BITMAPINFOHEADER(biSize=ctypes.sizeof(_BITMAPINFOHEADER), biWidth=width, biHeight=-height,
                                       biPlanes=1, biBitCount=32, biCompression=0)
            pixels = ctypes.create_string_buffer(width * height * 4)
            if _gdi32.GetDIBits(mem_dc, bitmap, 0, height, pixels, ctypes.byref(header), 0) != height:
                return None
        finally:
            if previous:
                _gdi32.SelectObject(mem_dc, previous)
            if bitmap:
                _gdi32.DeleteObject(bitmap)
            if mem_dc:
                _gdi32.DeleteDC(mem_dc)
            if screen_dc:
                _user32.ReleaseDC(None, screen_dc)
        image = Image.frombuffer("RGB", (width, height), pixels.raw, "raw", "BGRX", 0, 1)
        left, top, right, bottom = info.rect
        box = (max(left - outer.left, 0), max(top - outer.top, 0), min(right - outer.left, width), min(bottom - outer.top, height))
        if box[2] - box[0] >= 50 and box[3] - box[1] >= 50:
            image = image.crop(box)
        return None if is_blank(image) else image
else:  # pragma: no cover - the pet targets Windows; other platforms just never capture.
    def foreground_window() -> WindowInfo | None:
        return None

    def window_info(hwnd: int) -> WindowInfo | None:
        return None

    def capture_window(info: WindowInfo) -> Image.Image | None:
        return None

    def idle_seconds() -> float | None:
        return None

    def notification_busy() -> bool:
        return False

    def is_fullscreen(info: WindowInfo | None) -> bool:
        return False
