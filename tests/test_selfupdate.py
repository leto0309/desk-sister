"""Downloading a new exe when 主人 asks: this repository's release only, checked, swapped after she quits."""
import hashlib
import io
import json
import os
import random
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from claude_pet import __version__, claude_client, updates
from claude_pet.config import Config

QtWidgets = pytest.importorskip("PySide6.QtWidgets")
from claude_pet import controller as controller_module  # noqa: E402

SPRITES = Path(__file__).resolve().parents[1] / "assets" / "sprites"
EXE = b"MZ" + bytes(range(256)) * 400
SHA = hashlib.sha256(EXE).hexdigest()
TAG = "v9.0.0"
URL = f"{updates.DOWNLOAD_PREFIX}{TAG}/desk-sister.exe"


class Answer(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()


def release(**asset):
    item = {"name": "desk-sister.exe", "browser_download_url": URL, "size": len(EXE), "digest": f"sha256:{SHA}"}
    item.update(asset)
    return {"tag_name": TAG, "assets": [{"name": "notes.txt"}, item]}


def opener_for(body):
    def opener(request, timeout):
        return Answer(body if isinstance(body, bytes) else json.dumps(body).encode())
    return opener


def test_fetch_asset():
    assert updates.fetch_asset(opener_for(release())) == updates.Asset("9.0.0", URL, len(EXE), SHA)


@pytest.mark.parametrize("asset", [
    {"browser_download_url": "https://github.com/someone/else/releases/download/v9.0.0/desk-sister.exe"},
    {"browser_download_url": f"{updates.DOWNLOAD_PREFIX}v8.0.0/desk-sister.exe"},  # another release's file
    {"browser_download_url": URL.replace("https", "http")},
    {"browser_download_url": URL + "?x=1"},
    {"digest": None}, {"digest": "sha1:abc"}, {"digest": f"sha256:{SHA.upper()}"},
    {"size": 0}, {"size": True}, {"size": "1"}, {"size": updates.MAX_EXE_BYTES + 1},
    {"name": "desk-sister-setup.exe"},
])
def test_fetch_asset_refuses(asset):
    assert updates.fetch_asset(opener_for(release(**asset))) is None


class Stream(io.BytesIO):
    def __init__(self, data, on_read=None):
        super().__init__(data)
        self.on_read = on_read

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()

    def read(self, size=-1):
        if self.on_read:
            self.on_read()
        return super().read(size)


def fetch(data, on_read=None, seen=None):
    def opener(request, timeout):
        if seen is not None:
            seen.append((request.full_url, request.data, timeout))
        return Stream(data, on_read)
    return opener


ASSET = updates.Asset("9.0.0", URL, len(EXE), SHA)


def test_download_checks_and_keeps_the_file(tmp_path):
    seen, progress = [], []
    path = updates.download(ASSET, tmp_path, lambda: False, lambda got, total: progress.append((got, total)),
                            fetch(EXE, seen=seen))
    assert path == tmp_path / updates.UPDATE_NAME and path.read_bytes() == EXE
    assert list(tmp_path.iterdir()) == [path]  # no part file left
    assert seen == [(URL, None, updates.DOWNLOAD_TIMEOUT_SEC)] and progress[-1] == (len(EXE), len(EXE))


@pytest.mark.parametrize("data", [EXE[:-1], EXE + b"x", b"x" + EXE[1:]], ids=["short", "long", "changed"])
def test_a_wrong_download_is_deleted(tmp_path, data):
    with pytest.raises(ValueError):
        updates.download(ASSET, tmp_path, lambda: False, lambda *_: None, fetch(data))
    assert list(tmp_path.iterdir()) == []


def test_cancel_deletes_the_part(tmp_path):
    reads = []
    with pytest.raises(updates.Cancelled):
        updates.download(ASSET, tmp_path, lambda: len(reads) >= 2, lambda *_: None, fetch(EXE, lambda: reads.append(1)))
    assert list(tmp_path.iterdir()) == []


def test_an_unwritable_folder_fails_before_downloading(tmp_path):
    with pytest.raises(OSError):
        updates.download(ASSET, tmp_path / "missing", lambda: False, lambda *_: None,
                         lambda *_a, **_k: pytest.fail("downloaded anyway"))


def test_a_link_already_at_the_update_name_is_not_written_through(tmp_path):
    outside = tmp_path / "someone else's file"
    outside.write_bytes(b"keep me")
    folder = tmp_path / "app"
    folder.mkdir()
    os.link(outside, folder / updates.UPDATE_NAME)
    path = updates.download(ASSET, folder, lambda: False, lambda *_: None, fetch(EXE))
    assert path.read_bytes() == EXE and outside.read_bytes() == b"keep me"


def test_part_files_get_fresh_names(tmp_path, monkeypatch):
    names = []
    real = updates.tempfile.mkstemp
    monkeypatch.setattr(updates.tempfile, "mkstemp", lambda **kw: names.append(kw) or real(**kw))
    updates.download(ASSET, tmp_path, lambda: False, lambda *_: None, fetch(EXE))
    assert names == [{"prefix": updates.PART_PREFIX, "suffix": updates.PART_SUFFIX, "dir": tmp_path}]


def test_cancelled_during_the_last_read(tmp_path):
    state = {"eof": False}

    class Last(Stream):
        def read(self, size=-1):
            chunk = super().read(size)
            state["eof"] = state["eof"] or not chunk
            return chunk

    with pytest.raises(updates.Cancelled):
        updates.download(ASSET, tmp_path, lambda: state["eof"], lambda *_: None, lambda *_a, **_k: Last(EXE))
    assert list(tmp_path.iterdir()) == []


def test_remove_leftovers(tmp_path):
    assert updates.remove_leftovers(tmp_path) == ""
    for name in (f"{updates.PART_PREFIX}abc{updates.PART_SUFFIX}", updates.OLD_NAME, "desk-sister.exe"):
        (tmp_path / name).write_bytes(b"x")
    assert updates.remove_leftovers(tmp_path) == ""
    assert [p.name for p in tmp_path.iterdir()] == ["desk-sister.exe"]
    (tmp_path / updates.UPDATE_NAME).write_bytes(b"x")  # a download that never went in
    assert updates.remove_leftovers(tmp_path) == "restored"
    assert [p.name for p in tmp_path.iterdir()] == ["desk-sister.exe"]


def test_the_backup_stays_while_the_note_cannot_be_deleted(tmp_path, monkeypatch):
    (tmp_path / updates.RESULT_NAME).write_text("updated", encoding="ascii")
    (tmp_path / updates.OLD_NAME).write_bytes(b"x")
    real = Path.unlink

    def held(self, missing_ok=False):
        if self.name == updates.RESULT_NAME:
            raise PermissionError("in use")
        real(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", held)
    assert updates.remove_leftovers(tmp_path) == "updated"
    monkeypatch.undo()
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted([updates.OLD_NAME, updates.RESULT_NAME])


def test_a_file_that_cannot_be_deleted_does_not_hide_the_result(tmp_path, monkeypatch):
    (tmp_path / updates.RESULT_NAME).write_text("updated", encoding="ascii")
    (tmp_path / updates.OLD_NAME).write_bytes(b"x")
    (tmp_path / f"{updates.PART_PREFIX}x{updates.PART_SUFFIX}").write_bytes(b"x")
    real = Path.unlink

    def held(self, missing_ok=False):
        if self.name != updates.RESULT_NAME:
            raise PermissionError("in use")
        real(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", held)
    assert updates.remove_leftovers(tmp_path) == "updated"
    monkeypatch.undo()
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted([updates.OLD_NAME, f"{updates.PART_PREFIX}x{updates.PART_SUFFIX}"])


@pytest.mark.parametrize(("note", "result"), [
    (b"updated\r\n", "updated"), (b"restored", "restored"), (b"failed\r\n", "failed"), (b"rm -rf", ""),
    (b"\xff\xfe", ""),
])
def test_the_helper_s_note_is_read_once(tmp_path, note, result):
    (tmp_path / updates.RESULT_NAME).write_bytes(note)
    assert updates.remove_leftovers(tmp_path) == result
    assert list(tmp_path.iterdir()) == []


def test_restart_env_drops_the_one_file_variables():
    base = {"PATH": "p", "_PYI_ARCHIVE_FILE": "a", "_MEIPASS2": "m", "_pyi_x": "y", "APPDATA": "d",
            "PSModulePath": r"C:\Program Files\PowerShell\Modules"}
    env = updates.restart_env(base, Path("C:/A B/desk-sister.exe"), Path("C:/A B/new.exe"), SHA, [12, 34])
    assert env == {"PATH": "p", "APPDATA": "d", "PYINSTALLER_RESET_ENVIRONMENT": "1",
                   "DS_EXE": str(Path("C:/A B/desk-sister.exe")), "DS_NEW": str(Path("C:/A B/new.exe")),
                   "DS_OLD": str(Path("C:/A B") / updates.OLD_NAME), "DS_SHA": SHA.upper(), "DS_WAIT": "12,34",
                   "DS_RESULT": str(Path("C:/A B") / updates.RESULT_NAME)}


def stand_ins(tmp_path):
    """Two runnable programs told apart by an overlay after the program, and a script that records which ran."""
    folder = tmp_path / "it's a folder; with spaces"
    folder.mkdir()
    exe, new = folder / "desk-sister.exe", folder / updates.UPDATE_NAME
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    for path, tag in ((exe, b"old version"), (new, b"new version")):
        shutil.copyfile(pythonw if pythonw.is_file() else sys.executable, path)
        with open(path, "ab") as out:
            out.write(tag)
    venv = Path(sys.prefix, "pyvenv.cfg")
    if venv.is_file():  # a venv's python needs its pyvenv.cfg beside it
        shutil.copyfile(venv, folder / "pyvenv.cfg")
    marker = folder / "started.txt"
    # Like the real exe: take the helper's note as it starts (kept aside here for the test to read). A copy whose
    # tag is in DS_TEST_CRASH quits at once instead, as a broken new version would.
    (folder / "__main__.py").write_text(f"""import os, shutil, sys
tag = open(sys.executable, "rb").read()[-11:]
if tag.decode() == os.environ.get("DS_TEST_CRASH"):
    import time
    time.sleep(float(os.environ.get("DS_TEST_CRASH_AFTER") or 0))  # up a while, but never ready
    if os.environ.get("DS_TEST_DROP_OLD"):
        os.remove(os.environ["DS_OLD"])  # as if the backup had been cleaned away
    sys.exit(3)
result = os.environ["DS_RESULT"]
if os.path.exists(result):
    shutil.copyfile(result, {str(folder / "seen-result.txt")!r})
    os.remove(result)
open({str(marker)!r}, "wb").write(tag)
""", encoding="utf-8")
    return folder, exe, new, marker


def run_helper(folder, exe, new, sha, wait, failing=(), crash="", drop_old=False, crash_after=0):
    """Run the real script; `failing` holds PowerShell functions put in front of it that shadow a command and
    fail (as if a file were held open)."""
    env = updates.restart_env(dict(os.environ), exe, new, sha, wait)
    script = updates.RESTART_SCRIPT.replace(  # the stand-in is told which folder's __main__.py to run
        "Start-Process -FilePath $env:DS_EXE", "Start-Process -FilePath $env:DS_EXE -ArgumentList ('\"' + $env:DS_DIR + '\"')")
    script = script.replace("Start-Sleep -Seconds 1", "Start-Sleep -Milliseconds 20")
    script = "".join(line + "\n" for line in failing) + script
    assert "-ArgumentList" in script
    proc = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                           "-Command", script], env={**env, "DS_DIR": str(folder), "DS_TEST_CRASH": crash,
                                                       "DS_TEST_DROP_OLD": "1" if drop_old else "",
                                                       "DS_TEST_CRASH_AFTER": str(crash_after)},
                          capture_output=True, timeout=180)
    assert proc.returncode == 0, proc.stderr


def note(folder):
    """The helper's note: as the started copy took it, or still lying there if nothing took it."""
    for path in (folder / "seen-result.txt", folder / updates.RESULT_NAME):
        if path.exists():
            return path.read_text(encoding="ascii").strip()
    return None


def started(marker):
    for _ in range(100):
        if marker.exists() and marker.stat().st_size:
            return marker.read_bytes()
        time.sleep(0.1)
    return None


windows_only = pytest.mark.skipif(sys.platform != "win32", reason="the helper is Windows PowerShell")


@windows_only
def test_the_restart_script_waits_swaps_and_starts(tmp_path):
    folder, exe, new, marker = stand_ins(tmp_path)
    sha = updates.file_sha256(new)
    waiting = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(3)"])
    begun = time.monotonic()
    run_helper(folder, exe, new, sha, [waiting.pid])
    assert time.monotonic() - begun >= 2 and waiting.poll() is not None  # it waited for the process
    assert exe.read_bytes().endswith(b"new version") and not new.exists()
    assert (folder / updates.OLD_NAME).read_bytes().endswith(b"old version")  # kept until the new one starts
    assert started(marker) == b"new version" and note(folder) == "updated"


PWSH_MODULES = [p for p in (Path(os.environ.get("ProgramFiles", "C:/Program Files"), "PowerShell", "7", "Modules"),
                            Path.home() / "ai-dev-factory" / "tools" / "powershell" / "Modules") if p.is_dir()]


@windows_only
@pytest.mark.skipif(not PWSH_MODULES, reason="no PowerShell 7 here")
def test_started_from_a_powershell_7_terminal(tmp_path, monkeypatch):
    """PowerShell 7's module path, inherited by Windows PowerShell, breaks Get-FileHash: the helper must not get it."""
    monkeypatch.setenv("PSModulePath", os.pathsep.join(map(str, PWSH_MODULES)))
    folder, exe, new, marker = stand_ins(tmp_path)
    run_helper(folder, exe, new, updates.file_sha256(new), [])
    assert exe.read_bytes().endswith(b"new version")
    assert started(marker) == b"new version" and note(folder) == "updated"


@windows_only
def test_a_changed_download_is_not_installed(tmp_path):
    folder, exe, new, marker = stand_ins(tmp_path)
    run_helper(folder, exe, new, "0" * 64, [])
    assert exe.read_bytes().endswith(b"old version") and not (folder / updates.OLD_NAME).exists()
    assert started(marker) == b"old version" and note(folder) == "restored"


@windows_only
def test_unreadable_after_moving_in_puts_the_old_exe_back(tmp_path):
    folder, exe, new, marker = stand_ins(tmp_path)
    # An alias: Get-FileHash is itself a module function, which the module's autoload would put back.
    run_helper(folder, exe, new, updates.file_sha256(new), [],
               failing=["function Fail-Step { throw 'stand-in failure' }", "Set-Alias Get-FileHash Fail-Step"])
    assert exe.read_bytes().endswith(b"old version") and not (folder / updates.OLD_NAME).exists()
    assert started(marker) == b"old version" and note(folder) == "restored"


@windows_only
def test_an_unchecked_exe_that_cannot_be_removed_is_never_started(tmp_path):
    folder, exe, new, marker = stand_ins(tmp_path)
    run_helper(folder, exe, new, "0" * 64, [], failing=["function Remove-Item { throw 'stand-in failure' }"])
    assert exe.read_bytes().endswith(b"new version")  # still there: but not started
    assert (folder / updates.OLD_NAME).read_bytes().endswith(b"old version")  # the backup is kept
    assert started(marker) is None and note(folder) == "failed"


@windows_only
def test_an_exe_that_cannot_be_moved_aside_starts_as_it_is(tmp_path):
    folder, exe, new, marker = stand_ins(tmp_path)
    run_helper(folder, exe, new, updates.file_sha256(new), [],
               failing=["function Move-Item($LiteralPath, $Destination) {"
                        " if ($Destination -eq $env:DS_OLD) { throw 'stand-in failure' }"
                        r" Microsoft.PowerShell.Management\Move-Item -LiteralPath $LiteralPath -Destination $Destination }"])
    assert exe.read_bytes().endswith(b"old version") and new.exists()
    assert started(marker) == b"old version" and note(folder) == "restored"


@windows_only
def test_a_new_exe_that_will_not_start_puts_the_old_one_back(tmp_path):
    folder, exe, new, marker = stand_ins(tmp_path)
    blocked = ("function Start-Process($FilePath, $WorkingDirectory, $ArgumentList) {"
               " $b = [IO.File]::ReadAllBytes($FilePath);"
               " if ([Text.Encoding]::ASCII.GetString($b, $b.Length - 11, 11) -eq 'new version') { throw 'blocked' }"
               r" Microsoft.PowerShell.Management\Start-Process -FilePath $FilePath"
               " -WorkingDirectory $WorkingDirectory -ArgumentList $ArgumentList }")
    run_helper(folder, exe, new, updates.file_sha256(new), [], failing=[blocked])
    assert exe.read_bytes().endswith(b"old version") and not (folder / updates.OLD_NAME).exists()
    assert started(marker) == b"old version" and note(folder) == "restored"


@windows_only
def test_a_new_exe_that_quits_at_once_puts_the_old_one_back(tmp_path):
    folder, exe, new, marker = stand_ins(tmp_path)
    run_helper(folder, exe, new, updates.file_sha256(new), [], crash="new version")
    assert exe.read_bytes().endswith(b"old version") and not (folder / updates.OLD_NAME).exists()
    assert started(marker) == b"old version" and note(folder) == "restored"


@windows_only
def test_a_new_exe_that_runs_a_while_but_never_gets_ready_puts_the_old_one_back(tmp_path):
    folder, exe, new, marker = stand_ins(tmp_path)
    run_helper(folder, exe, new, updates.file_sha256(new), [], crash="new version", crash_after=4)
    assert exe.read_bytes().endswith(b"old version")
    assert started(marker) == b"old version" and note(folder) == "restored"


def test_waiting_for_her_to_quit_has_no_time_limit():
    body = updates.RESTART_SCRIPT[:updates.RESTART_SCRIPT.index("$state = ")]
    assert "WaitForExit()" in body and "-Timeout" not in body


def test_readiness_has_no_time_limit():
    body = updates.RESTART_SCRIPT[updates.RESTART_SCRIPT.index("function Start-Checked"):]
    body = body[:body.index("\n}\n")]
    assert "while ($true)" in body and "-lt" not in body


QUARANTINE = ("function Remove-Exe { Microsoft.PowerShell.Management\\Remove-Item -LiteralPath $env:DS_EXE }",)


@windows_only
def test_a_new_exe_taken_away_at_start_puts_the_old_one_back(tmp_path):
    folder, exe, new, marker = stand_ins(tmp_path)
    taken = QUARANTINE + (
        "function Start-Process($FilePath, $WorkingDirectory, $ArgumentList) {"
        " $b = [IO.File]::ReadAllBytes($FilePath);"
        " if ([Text.Encoding]::ASCII.GetString($b, $b.Length - 11, 11) -eq 'new version') { Remove-Exe; throw 'quarantined' }"
        r" Microsoft.PowerShell.Management\Start-Process -FilePath $FilePath"
        " -WorkingDirectory $WorkingDirectory -ArgumentList $ArgumentList }",)
    run_helper(folder, exe, new, updates.file_sha256(new), [], failing=taken)
    assert exe.read_bytes().endswith(b"old version") and not (folder / updates.OLD_NAME).exists()
    assert started(marker) == b"old version" and note(folder) == "restored"


@windows_only
def test_a_new_exe_taken_away_before_its_check_puts_the_old_one_back(tmp_path):
    folder, exe, new, marker = stand_ins(tmp_path)
    taken = QUARANTINE + ("function Fail-Step { Remove-Exe; throw 'quarantined' }", "Set-Alias Get-FileHash Fail-Step")
    run_helper(folder, exe, new, updates.file_sha256(new), [], failing=taken)
    assert exe.read_bytes().endswith(b"old version") and not (folder / updates.OLD_NAME).exists()
    assert started(marker) == b"old version" and note(folder) == "restored"


@windows_only
def test_without_a_backup_the_new_exe_is_never_removed(tmp_path):
    folder, exe, new, marker = stand_ins(tmp_path)
    run_helper(folder, exe, new, updates.file_sha256(new), [], crash="new version", drop_old=True)
    assert exe.read_bytes().endswith(b"new version")  # at least one exe is left
    assert started(marker) is None and note(folder) == "failed"


@windows_only
def test_without_the_note_the_old_exe_goes_back(tmp_path):
    folder, exe, new, marker = stand_ins(tmp_path)
    run_helper(folder, exe, new, updates.file_sha256(new), [],
               failing=["function Fail-Step { throw 'stand-in failure' }", "Set-Alias Set-Content Fail-Step"])
    assert exe.read_bytes().endswith(b"old version") and not (folder / updates.OLD_NAME).exists()
    assert started(marker) == b"old version" and note(folder) is None


@windows_only
def test_a_locked_download_leaves_the_old_exe_in_place(tmp_path):
    folder, exe, new, marker = stand_ins(tmp_path)
    with open(new, "rb"):  # held open without delete sharing: it cannot be moved
        run_helper(folder, exe, new, updates.file_sha256(new), [])
    assert exe.read_bytes().endswith(b"old version") and new.exists()
    assert started(marker) == b"old version" and note(folder) == "restored"


# ---- the pet ---------------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def pet(app, tmp_path, monkeypatch):
    for name, value in (("idle_seconds", lambda: 0.0), ("is_fullscreen", lambda _i: False),
                        ("notification_busy", lambda: False)):
        monkeypatch.setattr(controller_module.capture, name, value)
    monkeypatch.setattr(claude_client, "find_claude", lambda _configured="": "claude.exe")
    monkeypatch.setattr(controller_module, "save_config", lambda *_a, **_k: None)
    monkeypatch.setattr(controller_module, "app_data_dir", lambda: tmp_path)
    asked = []
    monkeypatch.setattr(updates, "fetch_asset", lambda name=updates.ASSET_NAME: asked.append(name) or ASSET)
    monkeypatch.setattr(updates, "download", lambda asset, folder, cancelled, progress, final_name=updates.UPDATE_NAME:
                        updates.__dict__["_real_download"](asset, folder, cancelled, progress, fetch(EXE),
                                                           final_name=final_name))
    updates._real_download = real_download
    folder = tmp_path / "app"
    folder.mkdir()
    exe = folder / "desk-sister.exe"
    exe.write_bytes(b"old")
    config = Config(greeted_on="2099-01-01", check_updates=False, update_latest="9.0.0", update_seen="9.0.0")
    ctrl = controller_module.PetController(app, config, SPRITES, tmp_path / "config.json")
    monkeypatch.setattr(ctrl, "_ask_claude", lambda *_a: pytest.fail("no model calls here"))
    ctrl._rng = random.Random(1)
    ctrl._exe_path = lambda: exe
    ctrl._spawn = lambda fn: fn()
    answers, launched, quits, scripts = [], [], [], []
    ctrl._confirm = lambda _title, _text: answers.pop(0)
    ctrl._launch_restart = lambda env, script=updates.RESTART_SCRIPT: launched.append(env) or scripts.append(script)
    ctrl._uses_installer = lambda: False  # a portable single-file exe unless a test says otherwise
    ctrl.asked, ctrl.scripts = asked, scripts
    ctrl.request_quit = lambda: quits.append(1)
    yield ctrl, exe, answers, launched, quits
    del updates._real_download
    if ctrl.settings_window is not None:
        ctrl.settings_window.close()


real_download = updates.download


def test_download_then_restart(pet):
    ctrl, exe, answers, launched, quits = pet
    assert ctrl.can_self_update and ctrl.update_available == "9.0.0"
    answers.append(True)
    ctrl.update_action()
    new = exe.parent / updates.UPDATE_NAME
    assert new.read_bytes() == EXE and ctrl.download_state == "ready"
    (env,) = launched
    assert (env["DS_EXE"], env["DS_NEW"]) == (str(exe), str(new)) and str(os.getpid()) in env["DS_WAIT"].split(",")
    assert env["DS_SHA"] == SHA.upper()
    assert env["PYINSTALLER_RESET_ENVIRONMENT"] == "1" and quits == [1]


def test_later_then_the_button_restarts(pet):
    ctrl, _exe, answers, launched, quits = pet
    answers.append(False)
    ctrl.update_action()
    assert ctrl.download_state == "ready" and "重启并更新" in ctrl.download_text and launched == [] and quits == []
    answers.append(True)
    ctrl.update_action()
    assert len(launched) == 1 and quits == [1]


def test_cancel(pet, monkeypatch):
    ctrl, exe, _answers, launched, _quits = pet
    jobs = []
    ctrl._spawn = jobs.append
    ctrl.update_action()
    assert ctrl.download_state == "downloading"
    ctrl.update_action()  # the button now says 取消下载
    jobs[0]()
    assert ctrl.download_state == "" and ctrl.download_text == "已取消下载。" and launched == []
    assert sorted(p.name for p in exe.parent.iterdir()) == ["desk-sister.exe"]


@pytest.mark.parametrize(("failure", "text"), [
    ("no asset", "读不到新版的下载信息"),
    ("not newer", "已是最新版"),
    (ValueError("checksum"), "不一致，已删除"),
    (PermissionError("denied"), "不能写入"),
    (OSError("reset"), "下载失败"),
    (RuntimeError("bug"), "下载失败"),
])
def test_failures_end_the_download(pet, monkeypatch, failure, text):
    ctrl, _exe, _answers, launched, quits = pet
    if failure == "no asset":
        monkeypatch.setattr(updates, "fetch_asset", lambda name=None: None)
    elif failure == "not newer":
        monkeypatch.setattr(updates, "fetch_asset", lambda name=None: updates.Asset(__version__, URL, 1, SHA))
    else:
        def broken(*_a, **_k):
            raise failure
        monkeypatch.setattr(updates, "download", broken)
    ctrl.update_action()
    assert ctrl.download_state == "" and text in ctrl.download_text and launched == [] and quits == []


def test_progress_is_shown_in_whole_percent(pet):
    ctrl, *_ = pet
    ctrl.download_state = "downloading"
    ctrl._on_download_progress(512 * 1024, 2 * 1048576)
    assert ctrl.download_text == "正在下载 25%（0.5 / 2.0 MB）"
    ctrl.download_text = "same percent: not redrawn"
    ctrl._on_download_progress(513 * 1024, 2 * 1048576)
    assert ctrl.download_text == "same percent: not redrawn"


def test_a_download_changed_after_the_check_is_not_installed(pet):
    ctrl, exe, answers, launched, quits = pet
    answers.append(False)
    ctrl.update_action()
    new = exe.parent / updates.UPDATE_NAME
    new.write_bytes(b"MZ something else")
    answers.append(True)
    ctrl.update_action()
    assert launched == [] and quits == [] and not new.exists() and "被改动" in ctrl.download_text


def test_cancelled_while_the_result_was_on_its_way(pet, monkeypatch):
    ctrl, exe, _answers, launched, _quits = pet
    finished = updates.download

    def then_cancel(*args, **kwargs):
        path = finished(*args, **kwargs)
        ctrl._download_cancel.set()  # 主人 clicks 取消 just as the download completes
        return path

    monkeypatch.setattr(updates, "download", then_cancel)
    ctrl.update_action()
    assert ctrl.download_state == "" and ctrl.download_text == "已取消下载。" and launched == []
    assert [p.name for p in exe.parent.iterdir()] == ["desk-sister.exe"]


def test_a_cancelled_download_that_cannot_be_removed_still_ends(pet, monkeypatch):
    ctrl, exe, _answers, launched, _quits = pet
    finished = updates.download

    def then_cancel(*args, **kwargs):
        path = finished(*args, **kwargs)
        ctrl._download_cancel.set()
        return path

    def held(self, missing_ok=False):
        raise PermissionError("in use")

    monkeypatch.setattr(updates, "download", then_cancel)
    monkeypatch.setattr(Path, "unlink", held)
    ctrl.update_action()
    assert ctrl.download_state == "" and "下次启动时会清理" in ctrl.download_text and launched == []


def test_a_vanished_download_is_not_swapped(pet):
    ctrl, exe, answers, launched, quits = pet
    answers.append(False)
    ctrl.update_action()
    (exe.parent / updates.UPDATE_NAME).unlink()
    answers.append(True)
    ctrl.update_action()
    assert launched == [] and quits == [] and ctrl.download_state == "" and "不见了" in ctrl.download_text


def test_a_helper_that_cannot_start_keeps_her_running(pet):
    ctrl, _exe, answers, _launched, quits = pet

    def fail(_env, _script=None):
        raise OSError("no powershell")

    ctrl._launch_restart = fail
    answers.append(True)
    ctrl.update_action()
    assert quits == [] and "没能启动更新程序" in ctrl.download_text


def test_a_held_note_is_removed_while_she_runs(pet, monkeypatch):
    ctrl, exe, *_ = pet
    note_file, backup = exe.parent / updates.RESULT_NAME, exe.parent / updates.OLD_NAME
    note_file.write_text("updated", encoding="ascii")
    backup.write_bytes(b"x")
    real, held = Path.unlink, [True]

    def unlink(self, missing_ok=False):
        if self.name == updates.RESULT_NAME and held[0]:
            raise PermissionError("in use")
        real(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", unlink)
    clock = [100.0]
    ctrl._clock = lambda: clock[0]
    ctrl.start()
    assert note_file.exists() and backup.exists() and "已更新" in ctrl.download_text
    ctrl._heartbeat()
    assert note_file.exists()  # still held
    held[0] = False
    ctrl._heartbeat()
    assert note_file.exists()  # not before the retry time
    clock[0] += controller_module.UPDATE_NOTE_RETRY_SEC
    ctrl._heartbeat()
    assert not note_file.exists() and not backup.exists() and not ctrl._update_note_retry
    assert "已更新" in ctrl.download_text  # what the about page said stays


def test_retrying_the_note_leaves_a_waiting_download_alone(pet, monkeypatch):
    ctrl, exe, answers, launched, _quits = pet
    note_file = exe.parent / updates.RESULT_NAME
    note_file.write_text("restored", encoding="ascii")
    real = Path.unlink

    def unlink(self, missing_ok=False):
        if self.name == updates.RESULT_NAME:
            raise PermissionError("in use")
        real(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", unlink)
    clock = [100.0]
    ctrl._clock = lambda: clock[0]
    ctrl.start()
    answers.append(False)  # downloaded, restart later
    ctrl.update_action()
    for _ in range(3):
        clock[0] += controller_module.UPDATE_NOTE_RETRY_SEC
        ctrl._heartbeat()
    assert (exe.parent / updates.UPDATE_NAME).read_bytes() == EXE and ctrl.download_state == "ready"
    answers.append(True)
    ctrl.update_action()
    assert len(launched) == 1


@pytest.mark.parametrize(("result", "text"), [
    ("updated", f"已更新到 {__version__}。"), ("restored", "没能换上"), ("failed", "手动下载"), ("", ""),
])
def test_leftovers_are_removed_at_start_and_the_outcome_shown(pet, result, text):
    ctrl, exe, *_ = pet
    (exe.parent / f"{updates.PART_PREFIX}x{updates.PART_SUFFIX}").write_bytes(b"x")
    (exe.parent / updates.OLD_NAME).write_bytes(b"x")
    if result:
        (exe.parent / updates.RESULT_NAME).write_text(result, encoding="ascii")
    ctrl.start()
    assert sorted(p.name for p in exe.parent.iterdir()) == ["desk-sister.exe"]
    assert text in ctrl.download_text and (text or ctrl.download_text == "")


def test_from_source_only_the_link(pet):
    ctrl, *_ = pet
    ctrl._exe_path = lambda: None
    assert not ctrl.can_self_update
    ctrl.update_action()
    assert ctrl.download_state == ""


def test_about_page_button(pet):
    ctrl, _exe, answers, _launched, _quits = pet
    ctrl.open_settings()
    window = ctrl.settings_window
    assert not window.update_button.isHidden() and window.update_button.text() == "下载并更新"
    answers.append(False)
    window.update_button.click()
    assert window.update_button.text() == "重启并更新" and "已下载并校验好" not in window.update_label.text()
    assert "重启并更新" in window.update_label.text()
    ctrl._exe_path = lambda: None
    ctrl.download_state = ""
    window.refresh()
    assert window.update_button.isHidden()


def test_the_bubble_points_at_the_button(pet):
    ctrl, *_ = pet
    ctrl.config.update_seen = ""
    ctrl._take_update("9.0.0")
    ctrl._announce_update()
    assert "下载并更新" in ctrl.window.full_text



# ---- the installer -------------------------------------------------------------------------------------------
def test_who_updates_through_the_installer(tmp_path):
    local = tmp_path / "Local"
    installed = local / "Programs" / "DeskSister"
    installed.mkdir(parents=True)
    exe = installed / "desk-sister.exe"
    assert updates.uses_installer(exe, str(installed / "_internal"), str(local))  # the one-folder build
    assert updates.uses_installer(tmp_path / "x" / "desk-sister.exe", str(tmp_path / "x" / "_internal"), None)
    assert updates.uses_installer(exe, str(tmp_path / "_MEI123"), str(local))  # single-file, where the installer goes
    temp = tmp_path / "Temp"  # a single-file exe run straight from %TEMP%: it unpacks next to itself
    assert not updates.uses_installer(temp / "desk-sister.exe", str(temp / "_MEI4242"), str(local))
    assert not updates.one_folder(temp / "desk-sister.exe", str(temp / "_MEI4242"))
    portable = tmp_path / "USB" / "desk-sister.exe"
    assert not updates.uses_installer(portable, str(tmp_path / "_MEI123"), str(local))
    assert not updates.uses_installer(portable, None, None)


def test_fetch_the_installer():
    url = f"{updates.DOWNLOAD_PREFIX}{TAG}/{updates.SETUP_NAME}"
    data = release()
    data["assets"].append({"name": updates.SETUP_NAME, "browser_download_url": url, "size": 10,
                           "digest": f"sha256:{SHA}"})
    assert updates.fetch_asset(opener_for(data), name=updates.SETUP_NAME) == updates.Asset("9.0.0", url, 10, SHA)
    data["assets"][-1]["browser_download_url"] = url.replace(updates.SETUP_NAME, "desk-sister.exe")
    assert updates.fetch_asset(opener_for(data), name=updates.SETUP_NAME) is None  # the name must match the address


def test_the_installed_copy_downloads_and_runs_the_installer(pet):
    ctrl, exe, answers, launched, quits = pet
    ctrl._uses_installer = lambda: True
    answers.append(True)
    ctrl.update_action()
    setup = exe.parent / updates.SETUP_UPDATE_NAME
    assert ctrl.asked == [updates.SETUP_NAME] and setup.read_bytes() == EXE
    assert not (exe.parent / updates.UPDATE_NAME).exists()
    (env,) = launched
    assert env["DS_NEW"] == str(setup) and env["DS_EXE"] == str(exe) and ctrl.scripts == [updates.SETUP_SCRIPT]
    assert quits == [1]


def test_a_portable_copy_still_swaps_the_exe(pet):
    ctrl, exe, answers, launched, _quits = pet
    answers.append(True)
    ctrl.update_action()
    assert ctrl.asked == [updates.ASSET_NAME] and ctrl.scripts == [updates.RESTART_SCRIPT]
    assert launched[0]["DS_NEW"] == str(exe.parent / updates.UPDATE_NAME)


def test_a_left_installer_download_is_cleaned_up(tmp_path):
    (tmp_path / updates.SETUP_UPDATE_NAME).write_bytes(b"x")
    assert updates.remove_leftovers(tmp_path) == "restored" and list(tmp_path.iterdir()) == []


def setup_stand_in(folder, exit_code):
    """A stand-in installer: a script that records its arguments and exits with `exit_code`."""
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    setup = folder / updates.SETUP_UPDATE_NAME
    shutil.copyfile(pythonw if pythonw.is_file() else sys.executable, setup)
    venv = Path(sys.prefix, "pyvenv.cfg")
    if venv.is_file():
        shutil.copyfile(venv, folder / "pyvenv.cfg")
    return setup


@windows_only
@pytest.mark.parametrize(("exit_code", "result"), [(0, "updated"), (3, "restored")])
def test_the_setup_script_runs_the_installer_quietly_then_starts_her(tmp_path, exit_code, result):
    folder, exe, _new, marker = stand_ins(tmp_path)
    setup = setup_stand_in(folder, exit_code)
    runner = folder / "installer_main"
    runner.mkdir()
    args_file = folder / "setup-args.txt"
    (runner / "__main__.py").write_text(
        f"import sys\nopen({str(args_file)!r}, 'w').write(' '.join(sys.argv[1:]))\nsys.exit({exit_code})\n",
        encoding="utf-8")
    env = updates.restart_env(dict(os.environ), exe, setup, updates.file_sha256(setup), [])
    script = updates.SETUP_SCRIPT.replace(  # the stand-in installer runs its folder's __main__.py, and so does she
        "-ArgumentList '/VERYSILENT'", "-ArgumentList ('\"' + $env:DS_RUNNER + '\"'), '/VERYSILENT'").replace(
        "Start-Process -FilePath $env:DS_EXE", "Start-Process -FilePath $env:DS_EXE -ArgumentList ('\"' + $env:DS_DIR + '\"')")
    proc = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command",
                           script], env={**env, "DS_DIR": str(folder), "DS_RUNNER": str(runner)}, capture_output=True,
                          timeout=120)
    assert proc.returncode == 0, proc.stderr
    assert args_file.read_text().split()[0:4] == ["/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-"]
    assert f"/DIR={folder}" in args_file.read_text()
    assert not setup.exists() and started(marker) == b"old version" and note(folder) == result


@windows_only
def test_the_setup_script_never_runs_a_changed_installer(tmp_path):
    folder, exe, _new, marker = stand_ins(tmp_path)
    setup = setup_stand_in(folder, 0)
    env = updates.restart_env(dict(os.environ), exe, setup, "0" * 64, [])
    script = updates.SETUP_SCRIPT.replace(
        "Start-Process -FilePath $env:DS_EXE", "Start-Process -FilePath $env:DS_EXE -ArgumentList ('\"' + $env:DS_DIR + '\"')")
    proc = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command",
                           script], env={**env, "DS_DIR": str(folder)}, capture_output=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    assert not (folder / "setup-args.txt").exists() and note(folder) == "restored" and started(marker) == b"old version"
