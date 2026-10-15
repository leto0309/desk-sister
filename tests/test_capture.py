import io

from PIL import Image

from claude_pet.capture import change_ratio, fingerprint, is_blocked, to_jpeg
from claude_pet.config import DEFAULT_BLOCKLIST


def test_blocklist_matches_title_or_process_case_insensitively():
    assert is_blocked("Bitwarden Vault", "Bitwarden.exe", DEFAULT_BLOCKLIST)
    assert is_blocked("新标签页", "WeChat.exe", DEFAULT_BLOCKLIST)
    assert is_blocked("招商银行 - Edge", "msedge.exe", DEFAULT_BLOCKLIST)
    assert is_blocked("New tab - InPrivate", "msedge.exe", DEFAULT_BLOCKLIST)
    assert not is_blocked("main.py - Visual Studio Code", "Code.exe", DEFAULT_BLOCKLIST)
    assert not is_blocked("anything", "x.exe", [""])


def test_jpeg_is_downscaled():
    data = to_jpeg(Image.new("RGBA", (3000, 1500), (200, 100, 50, 255)), max_side=1280)
    image = Image.open(io.BytesIO(data))
    assert image.format == "JPEG" and max(image.size) == 1280


def test_change_ratio_detects_real_changes_only():
    base = Image.new("RGB", (800, 600), "white")
    changed = base.copy()
    changed.paste(Image.new("RGB", (400, 300), "black"), (0, 0))
    assert change_ratio(None, fingerprint(base)) == 1.0
    assert change_ratio(fingerprint(base), fingerprint(base.copy())) == 0.0
    assert change_ratio(fingerprint(base), fingerprint(changed)) > 0.2


def test_full_screen_geometry_and_idle_tick_wraparound():
    from claude_pet.capture import covers_monitor, idle_from_ticks

    monitor = (0, 0, 1920, 1080)
    assert covers_monitor((0, 0, 1920, 1080), monitor)
    assert covers_monitor((-8, -8, 1928, 1088), monitor)  # an overhang still counts
    assert not covers_monitor((0, 0, 1920, 1040), monitor)  # maximised above the taskbar
    assert not covers_monitor((1920, 0, 3840, 1080), monitor)  # the other monitor
    assert idle_from_ticks(5000, 2000) == 3.0
    assert idle_from_ticks(1000, 0xFFFFFFFF - 999) == 2.0  # GetTickCount wrapped around


def test_real_machine_signals_have_the_right_types():
    import sys

    from claude_pet import capture

    if sys.platform != "win32":
        return
    idle = capture.idle_seconds()
    assert idle is None or idle >= 0
    assert isinstance(capture.notification_busy(), bool)
    assert capture.is_fullscreen(None) is False
