import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from claude_pet import agent_link, claude_client
from claude_pet.agent_link import (
    EVENT_FILE_REL, HOOK_SPECS, ClaudeCodeState, EventTail, HooksError, hook_handler, install_hooks,
    is_installed, uninstall_hooks,
)
from claude_pet.config import Config, load_config

USER_HOOK = {"type": "command", "command": "echo mine"}
SID_A = "0b8e6a1c-1111-4c2d-9e7f-aaaaaaaaaaaa"
SID_B = "5f3d2c1b-2222-4a5b-8c9d-bbbbbbbbbbbb"


def user_settings(path: Path) -> dict:
    data = {
        "model": "opus",
        "permissions": {"allow": ["Bash(git status)"]},
        "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [USER_HOOK]}], "Stop": [{"hooks": [USER_HOOK]}]},
    }
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return data


# ---- installing hooks -------------------------------------------------------------------------
def test_install_keeps_everything_else_and_is_idempotent(tmp_path):
    path = tmp_path / "settings.json"
    original = user_settings(path)
    backup = install_hooks(path)
    assert backup is not None and json.loads(backup.read_text(encoding="utf-8")) == original
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["model"] == "opus" and data["permissions"] == original["permissions"]
    assert data["hooks"]["PreToolUse"][0] == {"matcher": "Bash", "hooks": [USER_HOOK]}  # user hook untouched
    assert is_installed(path)
    ours = [h for groups in data["hooks"].values() for g in groups for h in g["hooks"] if h != USER_HOOK]
    assert len(ours) == len(HOOK_SPECS)
    install_hooks(path)  # again: no duplicates
    assert json.loads(path.read_text(encoding="utf-8")) == data
    assert not list(tmp_path.glob("*.claude-pet.tmp"))  # temp files cleaned up


def test_uninstall_removes_only_ours_and_backs_up(tmp_path):
    path = tmp_path / "settings.json"
    original = user_settings(path)
    install_hooks(path)
    installed = path.read_bytes()
    assert uninstall_hooks(path)
    assert json.loads(path.read_text(encoding="utf-8")) == original
    newest = sorted(tmp_path.glob("settings.json.claude-pet-backup-*"))[-1]
    assert newest.read_bytes() == installed  # the replaced version, in its own backup file
    assert not is_installed(path) and uninstall_hooks(path) is False
    fresh = tmp_path / "fresh" / "settings.json"
    assert install_hooks(fresh) is None  # created from nothing
    uninstall_hooks(fresh)
    assert json.loads(fresh.read_text(encoding="utf-8")) == {}
    assert uninstall_hooks(tmp_path / "missing.json") is False


def test_a_user_hook_that_mentions_our_event_file_is_kept(tmp_path):
    path = tmp_path / "settings.json"
    lookalike = {"type": "command", "command": "powershell.exe",
                 "args": ["-Command", f"Copy-Item (Join-Path $env:APPDATA '{EVENT_FILE_REL}') D:\\backup"]}
    path.write_text(json.dumps({"hooks": {"Stop": [{"hooks": [lookalike]}]}}), encoding="utf-8")
    install_hooks(path)
    uninstall_hooks(path)
    assert json.loads(path.read_text(encoding="utf-8")) == {"hooks": {"Stop": [{"hooks": [lookalike]}]}}


@pytest.mark.parametrize("content", [
    "{not json", "[1, 2]", '{"hooks": []}', '{"hooks": {"Stop": {}}}', '{"hooks": {"Stop": [3]}}',
    '{"hooks": {"Stop": [{"hooks": 123}]}}', '{"hooks": {"Stop": [{"hooks": [5]}]}}',
    '{"hooks": {"Stop": [{"matcher": 7, "hooks": []}]}}',
])
def test_broken_settings_are_never_modified(tmp_path, content):
    path = tmp_path / "settings.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(HooksError):
        install_hooks(path)
    with pytest.raises(HooksError):
        uninstall_hooks(path)
    assert path.read_text(encoding="utf-8") == content
    assert not is_installed(path)  # never raises


def test_a_concurrent_save_is_not_overwritten(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    user_settings(path)
    calls = []

    def someone_saves(target):
        calls.append(1)
        if len(calls) == 1:  # Claude Code saves a new permission right after we read the file
            data = json.loads(target.read_text(encoding="utf-8"))
            data["permissions"]["allow"].append("Read")
            target.write_text(json.dumps(data, indent=2), encoding="utf-8")

    monkeypatch.setattr(agent_link, "_before_commit", someone_saves)
    install_hooks(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert "Read" in data["permissions"]["allow"] and is_installed(path) and len(calls) == 2
    saves = []

    def keeps_saving(target):
        saves.append(1)
        target.write_text(json.dumps({"model": "sonnet", "save": len(saves)}), encoding="utf-8")

    monkeypatch.setattr(agent_link, "_before_commit", keeps_saving)
    with pytest.raises(HooksError):
        install_hooks(path)  # keeps changing under us: give up after 3 tries...
    assert len(saves) == 3
    assert json.loads(path.read_text(encoding="utf-8")) == {"model": "sonnet", "save": 3}  # ...without overwriting
    assert not list(tmp_path.glob("*.claude-pet.tmp"))


def test_settings_location_honours_claude_config_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    assert agent_link.claude_settings_path() == tmp_path / "settings.json"
    monkeypatch.delenv("CLAUDE_CONFIG_DIR")
    assert agent_link.claude_settings_path() == Path.home() / ".claude" / "settings.json"


@pytest.mark.skipif(sys.platform != "win32", reason="the hook runs powershell.exe")
def test_the_hook_writes_only_the_label_and_session(tmp_path):
    appdata = tmp_path / "App Data with space"
    (appdata / "ClaudePet" / "agent-events").mkdir(parents=True)
    handler = hook_handler("permission")
    assert handler["async"] is True and handler["command"] == "powershell.exe"
    assert all('"' not in arg for arg in handler["args"])  # nothing for a quoting layer to mangle
    env = {**os.environ, "APPDATA": str(appdata)}
    event = {"session_id": SID_A, "transcript_path": "C:\\x.jsonl", "hook_event_name": "Notification",
             "message": "Claude needs your permission: rm -rf secret-project; password=hunter2"}
    run = [handler["command"], *handler["args"]]
    subprocess.run(run, input=json.dumps(event), text=True, env=env, check=True, timeout=60, capture_output=True)
    subprocess.run(run, input="", text=True, env=env, check=True, timeout=60, capture_output=True)  # no stdin data
    text = (appdata / EVENT_FILE_REL.replace("\\", "/")).read_text(encoding="utf-8-sig")
    first, second = (line.split() for line in text.splitlines()[:2])
    assert first[:2] == ["permission", SID_A] and second[:2] == ["permission", "-"]
    assert first[2].isdigit() and int(second[2]) >= int(first[2])  # the hook process start time
    assert "secret" not in text and "hunter2" not in text and "rm -rf" not in text


# ---- reading events -------------------------------------------------------------------------------
def test_tail_reads_only_new_complete_known_lines(tmp_path):
    path = tmp_path / "claude.log"
    path.write_bytes(b"old\r\nprompt\r\n")
    tail = EventTail(path)  # starts at the end: old events are not replayed
    assert tail.read_new() == []
    with path.open("ab") as f:
        f.write(f"edit {SID_A}\r\nbogus x\r\nedit bad/id\r\nper".encode())
    assert tail.read_new() == [("edit", SID_A), ("edit", "")]  # unknown words ignored, odd ids dropped
    with path.open("ab") as f:
        f.write(b"mission\r\n")
    assert tail.read_new() == [("permission", "")]
    path.write_bytes(b"done\r\n")  # replaced by a shorter file
    assert tail.read_new() == [("done", "")]
    assert EventTail(tmp_path / "missing.log").read_new() == []


def test_tail_rotates_without_losing_a_racing_event(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_link, "MAX_EVENT_FILE", 64)
    path = tmp_path / "claude.log"
    path.write_bytes(b"")
    tail = EventTail(path)
    path.write_bytes(b"read\r\n" * 20)
    real_replace = agent_link.os.replace

    def append_then_rename(src, dst):
        with open(src, "ab") as f:  # a hook appends between our read and the rotation
            f.write(f"permission {SID_B}\r\n".encode())
        real_replace(src, dst)

    monkeypatch.setattr(agent_link.os, "replace", append_then_rename)
    events = tail.read_new()
    assert events[:20] == [("read", "")] * 20 and events[20:] == [("permission", SID_B)]
    assert not path.exists() and not (tmp_path / "claude.log.1").exists() and tail.offset == 0
    monkeypatch.setattr(agent_link.os, "replace", real_replace)
    path.write_bytes(b"done\r\n")
    assert tail.read_new() == [("done", "")]


def test_tail_waits_when_the_file_is_in_use(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_link, "MAX_EVENT_FILE", 8)
    path = tmp_path / "claude.log"
    path.write_bytes(b"")
    tail = EventTail(path)
    path.write_bytes(b"read\r\nread\r\n")

    def busy(*_a):
        raise PermissionError("a hook is writing")

    monkeypatch.setattr(agent_link.os, "replace", busy)
    assert tail.read_new() == [("read", ""), ("read", "")]
    assert path.read_bytes() == b"read\r\nread\r\n"  # nothing truncated or lost


# ---- state ----------------------------------------------------------------------------------------
def test_one_session_state_and_notices():
    state = ClaudeCodeState()
    assert state.feed("prompt", 100, SID_A) == [] and state.status() == "Claude Code 在思考…" and state.busy
    state.feed("edit", 101, SID_A)
    assert state.status() == "Claude Code 在改文件…"
    [notice] = state.feed("permission", 102, SID_A)
    assert notice.kind == "permission" and "批准" in notice.text and not state.busy
    assert state.feed("permission", 103, SID_A) == []  # not repeated while still waiting
    state.feed("run", 104, SID_A)
    [done] = state.feed("done", 130, SID_A)  # 30 s turn: announced
    assert done.kind == "done" and state.status() == ""
    state.feed("prompt", 200, SID_A)
    assert state.feed("done", 205, SID_A) == []  # a quick answer is not announced
    assert state.feed("waiting", 210, SID_A)[0].kind == "waiting"
    assert state.feed("error", 220, SID_A)[0].kind == "error"
    state.feed("read", 300, SID_A)
    state.tick(300 + agent_link.STALE_SEC + 1)
    assert not state.busy and state.status() == ""  # silent for a long time: over


def test_sessions_do_not_reset_each_other():
    state = ClaudeCodeState()
    state.feed("prompt", 100, SID_A)
    state.feed("edit", 101, SID_A)
    state.feed("start", 102, SID_B)  # a second session opens...
    state.feed("prompt", 103, SID_B)
    assert state.feed("done", 104, SID_B) == []  # ...answers quickly...
    state.feed("end", 105, SID_B)  # ...and closes
    assert state.busy and state.status() == "Claude Code 在改文件…"  # A is still working
    [done] = state.feed("done", 140, SID_A)
    assert done.kind == "done" and not state.busy  # A's long turn is still announced
    state.feed("prompt", 150, SID_A)
    state.feed("waiting", 151, SID_B)
    assert state.status() == "Claude Code 在等你回话"  # waiting for the user wins over busy


def test_claude_link_setting_defaults_off(tmp_path):
    path = tmp_path / "c.json"
    path.write_text(json.dumps({"claude_link": 1}), encoding="utf-8")
    assert load_config(path).claude_link is True and Config().claude_link is False


# ---- controller integration ---------------------------------------------------------------------
QtWidgets = pytest.importorskip("PySide6.QtWidgets")
from claude_pet import controller as controller_module  # noqa: E402

SPRITES = Path(__file__).resolve().parents[1] / "assets" / "sprites"


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def pet(app, tmp_path, monkeypatch):
    machine = {"idle": 0.0, "fullscreen": False}
    monkeypatch.setattr(controller_module.capture, "idle_seconds", lambda: machine["idle"])
    monkeypatch.setattr(controller_module.capture, "is_fullscreen", lambda _i: machine["fullscreen"])
    monkeypatch.setattr(controller_module.capture, "notification_busy", lambda: False)
    monkeypatch.setattr(claude_client, "find_claude", lambda _configured="": "claude.exe")
    monkeypatch.setattr(controller_module, "save_config", lambda *_a, **_k: None)
    monkeypatch.setattr(controller_module, "app_data_dir", lambda: tmp_path / "data")
    ctrl = controller_module.PetController(app, Config(dwell_sec=0), SPRITES, tmp_path / "config.json")
    ctrl.claude_settings = tmp_path / "claude" / "settings.json"
    asked = []
    ctrl._confirm = lambda title, text: asked.append(text) or True
    now = [1000.0]
    ctrl._clock = lambda: now[0]
    ctrl.target_since = 0.0  # set from the real clock in __init__: never let it lie in the fake clock's future
    events = tmp_path / "data" / "agent-events" / "claude.log"
    return ctrl, asked, events, now, machine


def emit(events: Path, *lines: str) -> None:
    with events.open("ab") as f:
        for line in lines:
            f.write(line.encode() + b"\r\n")


def beat(ctrl, now, times=1):
    for _ in range(times):
        now[0] += 1
        ctrl._heartbeat()


def test_enabling_asks_first_installs_hooks_and_starts_listening(pet):
    ctrl, asked, events, now, _machine = pet
    ctrl.set_claude_link(True)
    assert asked and "会话编号" in asked[0] and "不会被保存" in asked[0] and str(ctrl.claude_settings) in asked[0]
    assert ctrl.config.claude_link and is_installed(ctrl.claude_settings) and events.parent.is_dir()
    assert "联动开启" in ctrl.window.full_text
    assert not ctrl.claude_link_broken()
    ctrl.set_claude_link(False)
    assert not ctrl.config.claude_link and not is_installed(ctrl.claude_settings)


def test_declining_or_a_broken_settings_file_changes_nothing(pet):
    ctrl, _asked, _events, _now, _machine = pet
    ctrl._confirm = lambda *_a: False
    ctrl.set_claude_link(True)
    assert not ctrl.config.claude_link and not ctrl.claude_settings.exists()
    ctrl._confirm = lambda *_a: True
    ctrl.claude_settings.parent.mkdir(parents=True)
    ctrl.claude_settings.write_text("{oops", encoding="utf-8")
    ctrl.set_claude_link(True)
    assert not ctrl.config.claude_link and ctrl.claude_settings.read_text(encoding="utf-8") == "{oops"
    assert "没能开启联动" in ctrl.window.full_text


def test_events_become_status_and_notices(pet):
    ctrl, _asked, events, now, _machine = pet
    ctrl.set_claude_link(True)
    ctrl.window.clear_bubble()
    emit(events, f"prompt {SID_A}", f"edit {SID_A}")
    beat(ctrl, now)
    assert ctrl.window.status == "Claude Code 在改文件…" and ctrl.window.full_text == ""
    assert ctrl._auto_gate() == "Claude Code is working"  # no screen comments meanwhile
    emit(events, f"permission {SID_A}")
    beat(ctrl, now)
    assert "等你批准" in ctrl.window.full_text and ctrl.window.mood == "panic"
    emit(events, f"run {SID_A}")
    now[0] += 40
    beat(ctrl, now)
    ctrl.window.clear_bubble()
    emit(events, f"done {SID_A}")
    beat(ctrl, now)
    assert "做完啦" in ctrl.window.full_text and ctrl._auto_gate() is None


def test_a_notice_wakes_her_and_she_stays_awake_to_show_it(pet):
    ctrl, _asked, events, now, machine = pet
    ctrl.set_claude_link(True)
    machine["idle"] = 9999  # the user is away
    beat(ctrl, now)
    assert ctrl.asleep
    emit(events, f"permission {SID_A}")
    beat(ctrl, now, times=10)  # idle stays high for many heartbeats
    assert not ctrl.asleep and "等你批准" in ctrl.window.full_text and ctrl.window.mood == "panic"
    now[0] += controller_module.NOTICE_AWAKE_SEC
    beat(ctrl, now)
    assert ctrl.asleep  # after the grace period she may doze off again


def test_full_screen_holds_notices_even_when_watching_is_paused(pet):
    ctrl, _asked, events, now, machine = pet
    ctrl.set_claude_link(True)
    ctrl.toggle_pause()  # "stop watching the screen" must not silence Claude Code notices
    ctrl.window.clear_bubble()
    machine["fullscreen"] = True
    beat(ctrl, now)
    emit(events, f"prompt {SID_A}", f"permission {SID_A}")
    beat(ctrl, now)
    assert ctrl.window.full_text == "" and ctrl.deferred_notice is not None  # held (status shows "已暂停")
    machine["fullscreen"] = False
    beat(ctrl, now)
    assert "等你批准" in ctrl.window.full_text and ctrl.deferred_notice is None


def test_link_off_means_no_listening(pet):
    ctrl, _asked, events, now, _machine = pet
    events.parent.mkdir(parents=True)
    events.write_bytes(b"")
    emit(events, "prompt", "permission")
    beat(ctrl, now)
    assert ctrl.window.full_text == "" and ctrl._auto_gate() is None


@pytest.mark.skipif(sys.platform != "win32", reason="the hook runs powershell.exe")
def test_text_that_looks_like_a_session_id_is_never_picked_up(tmp_path):
    appdata = tmp_path / "appdata"
    (appdata / "ClaudePet" / "agent-events").mkdir(parents=True)
    handler = hook_handler("prompt")
    env = {**os.environ, "APPDATA": str(appdata)}
    run = [handler["command"], *handler["args"]]
    cases = [
        ('{"prompt": "my session_id: hunter2hunter2", "session_id": "' + SID_A + '"}', SID_A),  # any key order
        ('{"prompt": "你好「session_id」", "session_id": "' + SID_A + '"}', SID_A),  # non-ASCII text first
        ('{"x": {"session_id": "nestednested"}, "session_id": "' + SID_A + '"}', SID_A),  # top level only
        ('{"x": {"session_id": "nestednested"}}', ""),
        ('[{"session_id": "' + SID_A + '"}]', ""),  # not an object
        ('{"session_id": 123456789}', ""),  # not a string
        ('{"session_id": "abcdefgh\\nprompt"}', ""),  # never a second line
        ('"session_id": "notanobject123"', ""),
        ('{"session_id": "' + SID_B + '", "cut', SID_B),  # unparseable: only a leading key counts
    ]
    for payload, _expected in cases:
        subprocess.run(run, input=payload.encode("utf-8"), env=env, check=True, timeout=60, capture_output=True)
    text = (appdata / "ClaudePet" / "agent-events" / "claude.log").read_text(encoding="utf-8-sig")
    lines = [line.split()[:2] for line in text.splitlines() if line.strip()]
    assert lines == [["prompt", sid or "-"] for _payload, sid in cases]
    assert "hunter2" not in text and "nested" not in text and "notanobject" not in text and "abcdefgh" not in text


def test_a_save_that_slips_in_right_before_the_replace_is_kept(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    user_settings(path)
    slipped = []

    def save_now(target):
        if not slipped:  # Claude Code saves after our stale check, before our replace
            slipped.append(1)
            data = json.loads(target.read_text(encoding="utf-8"))
            data["permissions"]["allow"].append("WebSearch")
            target.write_text(json.dumps(data, indent=2), encoding="utf-8")

    monkeypatch.setattr(agent_link, "_before_replace", save_now)
    backup = install_hooks(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert "WebSearch" in data["permissions"]["allow"] and is_installed(path)  # their save survived
    assert "WebSearch" in json.loads(backup.read_text(encoding="utf-8"))["permissions"]["allow"]
    assert not list(tmp_path.glob("*.claude-pet.tmp"))


def test_hooks_from_the_first_version_are_migrated_and_removed(tmp_path):
    path = tmp_path / "settings.json"
    legacy = {"hooks": {"Stop": [{"hooks": [agent_link._legacy_handler_v1("done")]}],
                        "PreToolUse": [{"matcher": "Bash", "hooks": [USER_HOOK]}]}}
    path.write_text(json.dumps(legacy), encoding="utf-8")
    assert is_installed(path)
    install_hooks(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    handlers = [h for groups in data["hooks"].values() for g in groups for h in g["hooks"]]
    assert agent_link._legacy_handler_v1("done") not in handlers and handlers.count(hook_handler("done")) == 1
    assert USER_HOOK in handlers
    path.write_text(json.dumps(legacy), encoding="utf-8")
    uninstall_hooks(path)
    expected = {"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [USER_HOOK]}]}}
    assert json.loads(path.read_text(encoding="utf-8")) == expected


def test_a_failed_read_of_the_rotated_file_is_retried_once(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_link, "MAX_EVENT_FILE", 64)
    newline = bytes([13, 10])
    path = tmp_path / "claude.log"
    path.write_bytes(b"")
    tail = EventTail(path)
    path.write_bytes((b"read" + newline) * 20)
    real_replace, real_read = agent_link.os.replace, EventTail._read_from
    failures = []

    def append_then_rename(src, dst):
        with open(src, "ab") as f:
            f.write(b"done" + newline)
        real_replace(src, dst)

    def flaky_read(self, file, start):
        if file == self.rotated and not failures:
            failures.append(1)
            raise PermissionError("antivirus is scanning it")
        return real_read(self, file, start)

    monkeypatch.setattr(agent_link.os, "replace", append_then_rename)
    monkeypatch.setattr(EventTail, "_read_from", flaky_read)
    assert tail.read_new() == [("read", "")] * 20  # the event appended before the rename is still pending
    monkeypatch.setattr(agent_link.os, "replace", real_replace)
    path.write_bytes(b"edit" + newline)  # a new event in the new file
    assert tail.read_new() == [("done", ""), ("edit", "")]  # pending first, exactly once, in order
    assert tail.read_new() == [] and not tail.rotated.exists()


def test_events_without_a_session_never_touch_known_sessions():
    state = ClaudeCodeState()
    state.feed("prompt", 100, SID_A)
    state.feed("edit", 101, SID_A)
    for label in ("end", "done", "start", "prompt", "read"):  # source unknown
        assert state.feed(label, 102) == []
    assert state.busy and list(state.sessions) == [SID_A] and state.status() == "Claude Code 在改文件…"
    assert state.feed("permission", 103)[0].kind == "permission"  # still worth telling the user
    assert state.busy


def test_conflicts_before_the_check_and_a_slip_after_it_all_survive(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    user_settings(path)

    def add_permission(target, name):
        data = json.loads(target.read_text(encoding="utf-8"))
        data["permissions"]["allow"].append(name)
        target.write_text(json.dumps(data, indent=2), encoding="utf-8")

    commits, replaces = [], []
    monkeypatch.setattr(agent_link, "_before_commit",
                        lambda target: commits.append(1) or (len(commits) <= 2 and add_permission(target, f"pre{len(commits)}")))
    monkeypatch.setattr(agent_link, "_before_replace",
                        lambda target: replaces.append(1) or (len(replaces) == 1 and add_permission(target, "slipped")))
    install_hooks(path)
    allow = json.loads(path.read_text(encoding="utf-8"))["permissions"]["allow"]
    assert {"pre1", "pre2", "slipped"} <= set(allow) and is_installed(path)


def test_a_failing_second_swap_keeps_the_users_version_on_disk(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    user_settings(path)
    slipped, swaps = [], []
    real_swap = agent_link._swap

    def slip(target):
        if not slipped:
            slipped.append(1)
            data = json.loads(target.read_text(encoding="utf-8"))
            data["permissions"]["allow"].append("WebSearch")
            target.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def flaky_swap(target, temp, backup):
        swaps.append(1)
        if len(swaps) == 2:
            raise OSError(32, "the file is in use")
        real_swap(target, temp, backup)

    monkeypatch.setattr(agent_link, "_before_replace", slip)
    monkeypatch.setattr(agent_link, "_swap", flaky_swap)
    with pytest.raises(HooksError) as caught:
        install_hooks(path)
    message = str(caught.value)
    assert "已被桌宠改动" in message and "in use" in message  # truthful: the file did change
    named = Path(message.split("那个程序保存的版本在 ")[1].split("，")[0])
    assert named.exists() and "WebSearch" in json.loads(named.read_text(encoding="utf-8"))["permissions"]["allow"]


def test_backups_are_unique_and_pruned(tmp_path):
    path = tmp_path / "settings.json"
    user_settings(path)
    for _ in range(8):
        install_hooks(path)
        uninstall_hooks(path)
    backups = sorted(tmp_path.glob("settings.json.claude-pet-backup-*"))
    assert len(backups) == agent_link.BACKUP_KEEP and len({b.name for b in backups}) == agent_link.BACKUP_KEEP


def test_hooks_from_the_second_version_are_migrated_and_removed(tmp_path):
    path = tmp_path / "settings.json"
    old = {"hooks": {"Notification": [{"matcher": "permission_prompt", "hooks": [agent_link._legacy_handler_v2("permission")]}]}}
    path.write_text(json.dumps(old), encoding="utf-8")
    assert is_installed(path)
    install_hooks(path)
    handlers = [h for groups in json.loads(path.read_text(encoding="utf-8"))["hooks"].values() for g in groups for h in g["hooks"]]
    assert agent_link._legacy_handler_v2("permission") not in handlers and hook_handler("permission") in handlers
    path.write_text(json.dumps(old), encoding="utf-8")
    uninstall_hooks(path)
    assert json.loads(path.read_text(encoding="utf-8")) == {}


def test_a_failed_delete_of_the_rotated_file_never_repeats_events(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_link, "MAX_EVENT_FILE", 64)
    newline = bytes([13, 10])
    path = tmp_path / "claude.log"
    path.write_bytes(b"")
    tail = EventTail(path)
    path.write_bytes((b"read" + newline) * 20)
    real_replace = agent_link.os.replace
    real_unlink = Path.unlink
    blocked = []

    def append_then_rename(src, dst):
        with open(src, "ab") as f:
            f.write(b"error" + newline)
        real_replace(src, dst)

    def flaky_unlink(self, *args, **kwargs):
        if self.name == "claude.log.1" and not blocked:
            blocked.append(1)
            raise PermissionError("still open somewhere")
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(agent_link.os, "replace", append_then_rename)
    monkeypatch.setattr(Path, "unlink", flaky_unlink)
    first = tail.read_new()
    assert first[-1] == ("error", "") and first.count(("error", "")) == 1
    monkeypatch.setattr(agent_link.os, "replace", real_replace)
    assert tail.read_new() == []  # the error event is not delivered twice
    assert not tail.rotated.exists()  # and the delete was retried


def test_a_broken_concurrent_save_is_reported_truthfully(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    user_settings(path)
    slipped = []

    def broken_save(target):
        if not slipped:
            slipped.append(1)
            target.write_text("{half written", encoding="utf-8")

    monkeypatch.setattr(agent_link, "_before_replace", broken_save)
    with pytest.raises(HooksError) as caught:
        install_hooks(path)
    message = str(caught.value)
    assert "已被桌宠改动" in message and "没有修改" not in message
    named = Path(message.split("那个程序保存的版本在 ")[1].split("，")[0])
    assert named.read_text(encoding="utf-8") == "{half written"


def test_a_stuck_intermediate_backup_does_not_fail_a_good_commit(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    user_settings(path)
    slipped = []
    real_unlink = Path.unlink

    def slip(target):
        if not slipped:
            slipped.append(1)
            data = json.loads(target.read_text(encoding="utf-8"))
            data["permissions"]["allow"].append("WebSearch")
            target.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def stuck_unlink(self, *args, **kwargs):
        if ".claude-pet-backup-" in self.name:
            raise PermissionError("locked by an indexer")
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(agent_link, "_before_replace", slip)
    monkeypatch.setattr(Path, "unlink", stuck_unlink)
    backup = install_hooks(path)  # must not raise
    assert is_installed(path) and "WebSearch" in json.loads(path.read_text(encoding="utf-8"))["permissions"]["allow"]
    assert backup.exists()


def test_rapid_replaces_keep_the_newest_backups(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    user_settings(path)
    monkeypatch.setattr(agent_link.time, "time_ns", lambda: 1_000_000_000)  # all within the same instant
    versions = []
    for i in range(8):
        data = json.loads(path.read_text(encoding="utf-8"))
        data["model"] = f"v{i}"
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        versions.append(path.read_bytes())
        backup = install_hooks(path) if i % 2 == 0 else None
        if backup is None:
            backup_path = None
            uninstall_hooks(path)
        else:
            backup_path = backup
            assert backup_path.exists() and backup_path.read_bytes() == versions[-1]  # exactly what was replaced
    backups = sorted(tmp_path.glob("settings.json.claude-pet-backup-*"))
    assert len(backups) == agent_link.BACKUP_KEEP
    assert json.loads(backups[-1].read_bytes())["model"] == "v7"  # the newest one is kept


def test_backups_in_other_names_never_push_out_the_newest(tmp_path):
    path = tmp_path / "settings.json"
    user_settings(path)
    older = [tmp_path / f"settings.json.claude-pet-backup-20261014-12000{i}-0" for i in range(5)]
    for f in older + [tmp_path / "settings.json.claude-pet-backup"]:
        f.write_text("old", encoding="utf-8")
    replaced = path.read_bytes()
    backup = install_hooks(path)
    assert backup.exists() and backup.read_bytes() == replaced  # the newest backup survives pruning
    assert all(f.exists() for f in older)  # other names are left alone


@pytest.mark.parametrize("content", ["[]", '{"hooks": []}', '{"hooks": {"Stop": [{"hooks": 1}]}}'])
def test_a_concurrent_save_with_a_bad_shape_is_reported_truthfully(tmp_path, monkeypatch, content):
    path = tmp_path / "settings.json"
    user_settings(path)
    slipped = []

    def bad_save(target):
        if not slipped:
            slipped.append(1)
            target.write_text(content, encoding="utf-8")

    monkeypatch.setattr(agent_link, "_before_replace", bad_save)
    with pytest.raises(HooksError) as caught:
        install_hooks(path)
    message = str(caught.value)
    assert "已被桌宠改动" in message and "没有修改" not in message
    named = Path(message.split("那个程序保存的版本在 ")[1].split("，")[0])
    assert named.read_text(encoding="utf-8") == content


def test_lookalike_digit_names_are_left_alone(tmp_path):
    path = tmp_path / "settings.json"
    user_settings(path)
    odd = [tmp_path / ("settings.json.claude-pet-backup-" + ch * 20) for ch in ("²", "１")]
    for f in odd:
        f.write_text("not ours", encoding="utf-8")
    for _ in range(7):
        install_hooks(path)  # must not fail on the odd names...
        uninstall_hooks(path)
    assert all(f.read_text(encoding="utf-8") == "not ours" for f in odd)  # ...and must not touch them
    assert len(agent_link._backups(path)) == agent_link.BACKUP_KEEP


def test_a_settings_file_created_meanwhile_is_not_overwritten(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"  # does not exist yet
    created = []

    def someone_creates(target):
        if not created and not target.exists():
            created.append(1)
            target.write_text(json.dumps({"model": "opus", "permissions": {"allow": ["Read"]}}), encoding="utf-8")

    monkeypatch.setattr(agent_link, "_before_replace", someone_creates)
    install_hooks(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["model"] == "opus" and data["permissions"]["allow"] == ["Read"] and is_installed(path)


def test_an_unreadable_backup_after_a_successful_swap_is_reported_truthfully(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    user_settings(path)
    monkeypatch.setattr(agent_link.time, "sleep", lambda _s: None)
    real_read_bytes = Path.read_bytes

    def locked(self):
        if ".claude-pet-backup-" in self.name:
            raise PermissionError("locked by antivirus")
        return real_read_bytes(self)

    monkeypatch.setattr(Path, "read_bytes", locked)
    with pytest.raises(HooksError) as caught:
        install_hooks(path)
    message = str(caught.value)
    assert "已被桌宠改动" in message and "claude-pet-backup-" in message
    monkeypatch.undo()
    assert is_installed(path)  # it really did change



def test_the_settings_can_always_switch_listening_off(pet):
    ctrl, _asked, _events, _now, _machine = pet
    ctrl.set_claude_link(True)
    ctrl.claude_settings.write_text("{broken", encoding="utf-8")
    ctrl.open_settings()
    box = ctrl.settings_window.link_box
    assert ctrl.claude_link_broken() and box.isChecked() and "异常" in box.text()
    box.setChecked(False)  # unchecking it switches listening off
    ctrl.settings_window.close()
    assert not ctrl.config.claude_link and ctrl.claude_tail is None


def test_switching_off_drops_held_notices(pet):
    ctrl, _asked, events, now, machine = pet
    ctrl.set_claude_link(True)
    ctrl.window.clear_bubble()
    machine["fullscreen"] = True
    beat(ctrl, now)
    emit(events, f"prompt {SID_A}", f"permission {SID_A}")
    beat(ctrl, now)
    assert ctrl.deferred_notice is not None
    ctrl.set_claude_link(False)
    ctrl.window.clear_bubble()
    machine["fullscreen"] = False
    beat(ctrl, now)
    assert "批准" not in ctrl.window.full_text and ctrl.awake_until == 0.0


def test_a_notice_is_not_covered_by_an_old_automatic_comment(pet):
    from claude_pet.controller import Outcome

    ctrl, _asked, events, now, machine = pet
    ctrl.set_claude_link(True)
    machine["fullscreen"] = True
    beat(ctrl, now)
    ctrl._on_reply(Outcome(ctrl.generation, "reply", result=claude_client.ClaudeResult(True, "talk|旧的评论")))
    emit(events, f"prompt {SID_A}", f"permission {SID_A}")
    beat(ctrl, now)
    assert ctrl.deferred is not None and ctrl.deferred_notice is not None
    machine["fullscreen"] = False
    beat(ctrl, now, times=3)
    assert "批准" in ctrl.window.full_text and ctrl.deferred is None  # the stale comment was dropped
    ctrl.window.clear_bubble()
    machine["fullscreen"] = True
    beat(ctrl, now)
    ctrl._on_reply(Outcome(ctrl.generation, "reply", result=claude_client.ClaudeResult(True, "talk|又一条旧评论")))
    machine["fullscreen"] = False
    emit(events, f"waiting {SID_A}")  # a notice arriving on the very beat full screen ends
    beat(ctrl, now, times=2)
    assert "回话" in ctrl.window.full_text


def test_hooks_from_the_third_version_are_recognised(tmp_path):
    path = tmp_path / "settings.json"
    old = {"hooks": {"Stop": [{"hooks": [agent_link._legacy_handler_v3("done")]}]}}
    path.write_text(json.dumps(old), encoding="utf-8")
    assert is_installed(path)
    uninstall_hooks(path)
    assert json.loads(path.read_text(encoding="utf-8")) == {}


def test_no_event_folder_means_no_enabling(pet):
    ctrl, _asked, events, _now, _machine = pet
    events.parent.parent.mkdir(parents=True)
    events.parent.write_text("a file, not a folder", encoding="utf-8")
    ctrl.set_claude_link(True)
    assert not ctrl.config.claude_link and ctrl.claude_tail is None
    assert not ctrl.claude_settings.exists() and "没能开启" in ctrl.window.full_text


def test_a_running_automatic_look_never_covers_a_notice(pet):
    from claude_pet.controller import Outcome

    ctrl, _asked, events, now, _machine = pet
    ctrl.set_claude_link(True)
    ctrl.generation += 1  # an automatic look is on its way
    looking = ctrl.generation
    emit(events, f"prompt {SID_A}", f"permission {SID_A}")
    beat(ctrl, now)
    assert "批准" in ctrl.window.full_text
    ctrl._on_reply(Outcome(looking, "reply", result=claude_client.ClaudeResult(True, "talk|旧的评论")))
    assert "批准" in ctrl.window.full_text and "旧的评论" not in ctrl.window.full_text
    ctrl.generation += 1  # a chat started after the notice is still answered
    ctrl._on_reply(Outcome(ctrl.generation, "reply", force=True, result=claude_client.ClaudeResult(True, "talk|回答你")))
    assert "回答你" in ctrl.window.full_text


def test_a_new_notice_beats_an_older_held_one(pet):
    ctrl, _asked, events, now, machine = pet
    ctrl.set_claude_link(True)
    machine["fullscreen"] = True
    beat(ctrl, now)
    emit(events, f"prompt {SID_A}", f"permission {SID_A}")
    beat(ctrl, now)
    assert ctrl.deferred_notice is not None
    machine["fullscreen"] = False
    emit(events, f"error {SID_A}")  # arrives on the very beat full screen ends
    beat(ctrl, now, times=3)
    assert "出错" in ctrl.window.full_text and "批准" not in ctrl.window.full_text


def test_events_fired_before_a_handled_one_are_dropped(tmp_path):
    path = tmp_path / "claude.log"
    path.write_bytes(b"")
    tail = EventTail(path)
    emit(path, f"done {SID_A} 200", f"prompt {SID_A} 100", "waiting - 50",f"prompt {SID_B} 60")
    assert tail.read_new() == [("done", SID_A), ("waiting", ""), ("prompt", SID_B)]  # the late prompt is stale
    emit(path, f"prompt {SID_A} 150", f"prompt {SID_A} 300", f"edit {SID_A}")
    assert tail.read_new() == [("prompt", SID_A), ("edit", SID_A)]  # still stale in a later read; old lines kept
    state = ClaudeCodeState()
    state.feed("done", 1, SID_A)
    assert not state.busy


def test_a_second_save_during_recovery_is_not_merged_blindly(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    user_settings(path)
    saves = []

    def add_permission(target, name):
        data = json.loads(target.read_text(encoding="utf-8"))
        data["permissions"]["allow"].append(name)
        target.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def slip(target):  # one program saves before our first swap, another before our second
        saves.append(1)
        if len(saves) <= 2:
            add_permission(target, "WebSearch" if len(saves) == 1 else "Bash(ls)")

    monkeypatch.setattr(agent_link, "_before_replace", slip)
    with pytest.raises(HooksError) as caught:
        install_hooks(path)
    message = str(caught.value)
    assert "已被桌宠改动" in message
    named = sorted(tmp_path.glob("settings.json.claude-pet-backup-*"))
    assert len(named) == 2 and all(str(p) in message for p in named)  # both named in full
    allowed = [json.loads(p.read_text(encoding="utf-8"))["permissions"]["allow"] for p in named]
    assert any("WebSearch" in a for a in allowed) and any("Bash(ls)" in a for a in allowed)  # nothing lost silently



def test_the_watchdog_of_an_older_automatic_look_never_covers_a_notice(pet):
    ctrl, _asked, events, now, _machine = pet
    ctrl.set_claude_link(True)
    ctrl.generation += 1
    ctrl.busy = True  # an automatic look is stuck
    stuck = ctrl.generation
    emit(events, f"prompt {SID_A}", f"permission {SID_A}")
    beat(ctrl, now)
    assert "批准" in ctrl.window.full_text
    ctrl._watchdog(stuck, False)
    assert not ctrl.busy and "批准" in ctrl.window.full_text  # abandoned quietly


def test_a_bad_order_field_never_breaks_the_batch(tmp_path):
    path = tmp_path / "claude.log"
    path.write_bytes(b"")
    tail = EventTail(path)
    emit(path, "prompt abcdefgh ²", f"permission {SID_A} 5", "done abcdefgh 99999999999999999999999")
    assert tail.read_new() == [("prompt", "abcdefgh"), ("permission", SID_A), ("done", "abcdefgh")]


def test_an_event_file_that_cannot_be_written_means_no_enabling(pet):
    ctrl, _asked, events, _now, _machine = pet
    events.mkdir(parents=True)  # claude.log is a folder: the hooks could never append to it
    ctrl.set_claude_link(True)
    assert not ctrl.config.claude_link and not ctrl.claude_settings.exists() and "没能开启" in ctrl.window.full_text


@pytest.mark.parametrize("after", ["run", "prompt", "end"])
def test_a_held_permission_notice_is_dropped_once_answered(pet, after):
    ctrl, _asked, events, now, machine = pet
    ctrl.set_claude_link(True)
    ctrl.window.clear_bubble()
    machine["fullscreen"] = True
    beat(ctrl, now)
    emit(events, f"prompt {SID_A}", f"permission {SID_A}")
    beat(ctrl, now)
    emit(events, f"{after} {SID_A}")  # approved (or the session moved on) while the game was full screen
    beat(ctrl, now)
    machine["fullscreen"] = False
    beat(ctrl, now, times=3)
    assert "批准" not in ctrl.window.full_text and ctrl.deferred_notice is None


def test_a_held_permission_notice_still_waiting_is_shown(pet):
    ctrl, _asked, events, now, machine = pet
    ctrl.set_claude_link(True)
    machine["fullscreen"] = True
    beat(ctrl, now)
    emit(events, f"prompt {SID_A}", f"permission {SID_A}")
    beat(ctrl, now, times=2)
    machine["fullscreen"] = False
    beat(ctrl, now, times=2)
    assert "批准" in ctrl.window.full_text


@pytest.mark.parametrize("pair", [("waiting", "prompt"), ("permission", "run")])
def test_a_notice_answered_within_the_same_batch_is_not_shown(pet, pair):
    ctrl, _asked, events, now, machine = pet
    ctrl.set_claude_link(True)
    ctrl.window.clear_bubble()
    machine["fullscreen"] = True
    beat(ctrl, now)
    emit(events, f"prompt {SID_A}", *(f"{label} {SID_A}" for label in pair))
    machine["fullscreen"] = False  # read on the very beat full screen ends
    beat(ctrl, now, times=2)
    assert "批准" not in ctrl.window.full_text and "回话" not in ctrl.window.full_text
    ctrl.window.clear_bubble()
    emit(events, f"waiting {SID_A}", f"prompt {SID_A}")  # and when nothing is full screen
    beat(ctrl, now)
    assert "回话" not in ctrl.window.full_text


def test_one_sessions_notice_never_hides_anothers(pet):
    ctrl, _asked, events, now, machine = pet
    ctrl.set_claude_link(True)
    ctrl.window.clear_bubble()
    machine["fullscreen"] = True
    beat(ctrl, now)
    emit(events, f"prompt {SID_A}", f"permission {SID_A}")
    beat(ctrl, now)
    emit(events, f"prompt {SID_B}", f"permission {SID_B}")
    beat(ctrl, now)
    emit(events, f"run {SID_B}")  # B was approved; A still waits
    beat(ctrl, now)
    machine["fullscreen"] = False
    beat(ctrl, now, times=2)
    assert "批准" in ctrl.window.full_text


def test_asking_for_approval_wins_over_a_finished_task(pet):
    ctrl, _asked, events, now, machine = pet
    ctrl.set_claude_link(True)
    ctrl.window.clear_bubble()
    machine["fullscreen"] = True
    beat(ctrl, now)
    emit(events, f"prompt {SID_A}", f"permission {SID_A}", f"prompt {SID_B}")
    beat(ctrl, now)
    now[0] += 60
    emit(events, f"done {SID_B}")  # a long task finished later
    beat(ctrl, now)
    machine["fullscreen"] = False
    beat(ctrl, now, times=2)
    assert "批准" in ctrl.window.full_text


def test_a_finished_tool_ends_waiting_for_approval():
    state = ClaudeCodeState()
    state.feed("prompt", 100, SID_A)
    state.feed("run", 101, SID_A)
    state.feed("permission", 102, SID_A)
    assert not state.busy
    state.feed("after", 110, SID_A)  # approved, the command ran
    assert state.busy and state.status() == "Claude Code 在跑命令…"
    state.feed("done", 111, SID_A)
    assert not state.busy


def test_a_tool_finishing_first_still_means_working(tmp_path):
    path = tmp_path / "claude.log"
    path.write_bytes(b"")
    tail = EventTail(path)
    state = ClaudeCodeState()
    emit(path, f"after {SID_A} 300", f"run {SID_A} 200", f"prompt {SID_A} 100")  # hooks finished in reverse
    for label, session in tail.read_new():
        state.feed(label, 1, session)
    assert state.busy
    emit(path, f"done {SID_A} 400", f"after {SID_A} 350")  # fired before the done: never revives the turn
    for label, session in tail.read_new():
        state.feed(label, 2, session)
    assert not state.busy


def test_an_approved_tool_is_not_announced_after_full_screen(pet):
    ctrl, _asked, events, now, machine = pet
    ctrl.set_claude_link(True)
    ctrl.window.clear_bubble()
    machine["fullscreen"] = True
    beat(ctrl, now)
    emit(events, f"prompt {SID_A}", f"run {SID_A}", f"permission {SID_A}")
    beat(ctrl, now)
    emit(events, f"after {SID_A}")
    beat(ctrl, now)
    machine["fullscreen"] = False
    beat(ctrl, now, times=2)
    assert "批准" not in ctrl.window.full_text and ctrl.claude_state.busy


@pytest.mark.parametrize("sequence", [["done"], ["error", "prompt", "done"], ["done", "start"]])
def test_last_turns_news_is_dropped_by_a_new_turn(pet, sequence):
    ctrl, _asked, events, now, machine = pet
    ctrl.set_claude_link(True)
    ctrl.window.clear_bubble()
    machine["fullscreen"] = True
    beat(ctrl, now)
    emit(events, f"prompt {SID_A}")
    beat(ctrl, now)
    now[0] += 60  # a long turn: its end is news
    emit(events, *(f"{label} {SID_A}" for label in sequence))
    beat(ctrl, now)
    if sequence == ["done"]:
        emit(events, f"prompt {SID_A}")  # the user already read it and asked for more
        beat(ctrl, now)
    machine["fullscreen"] = False
    beat(ctrl, now, times=2)
    assert "做完" not in ctrl.window.full_text and "出错" not in ctrl.window.full_text


def test_news_is_dropped_even_when_the_new_prompt_arrives_late(pet):
    ctrl, _asked, events, now, machine = pet
    ctrl.set_claude_link(True)
    ctrl.window.clear_bubble()
    machine["fullscreen"] = True
    beat(ctrl, now)
    emit(events, f"prompt {SID_A} 50")
    beat(ctrl, now)
    now[0] += 60
    emit(events, f"done {SID_A} 100")  # a long turn finished
    beat(ctrl, now)
    emit(events, f"run {SID_A} 300", f"prompt {SID_A} 200")  # the next turn; its prompt hook finished last
    beat(ctrl, now)
    machine["fullscreen"] = False
    beat(ctrl, now, times=2)
    assert "做完" not in ctrl.window.full_text and ctrl.claude_state.busy


def test_working_after_a_tool_finished_first_blocks_automatic_looks(pet):
    ctrl, _asked, events, now, _machine = pet
    ctrl.set_claude_link(True)
    emit(events, f"after {SID_A} 300", f"run {SID_A} 200", f"prompt {SID_A} 100")
    beat(ctrl, now)
    assert ctrl.claude_state.busy and ctrl._auto_gate() is not None


@pytest.mark.parametrize("order", [["done", "after"], ["after", "done"], ["end", "run"]])
def test_a_tie_never_revives_a_finished_turn(tmp_path, order):
    path = tmp_path / "claude.log"
    path.write_bytes(b"")
    tail = EventTail(path)
    state = ClaudeCodeState()
    emit(path, f"prompt {SID_A} 100", *(f"{label} {SID_A} 400" for label in order))
    for label, session in tail.read_new():
        state.feed(label, 1, session)
    assert not state.busy


def test_an_old_error_is_dropped_when_the_next_turns_done_arrives_first(pet):
    ctrl, _asked, events, now, machine = pet
    ctrl.set_claude_link(True)
    ctrl.window.clear_bubble()
    machine["fullscreen"] = True
    beat(ctrl, now)
    emit(events, f"prompt {SID_A} 50", f"error {SID_A} 100")
    beat(ctrl, now)
    emit(events, f"done {SID_A} 300", f"prompt {SID_A} 200")  # a quick next turn; its prompt hook was last
    beat(ctrl, now)
    machine["fullscreen"] = False
    beat(ctrl, now, times=2)
    assert "出错" not in ctrl.window.full_text


def test_a_repeated_permission_keeps_the_held_notice(pet):
    ctrl, _asked, events, now, machine = pet
    ctrl.set_claude_link(True)
    ctrl.window.clear_bubble()
    machine["fullscreen"] = True
    beat(ctrl, now)
    emit(events, f"prompt {SID_A}", f"permission {SID_A}")
    beat(ctrl, now)
    emit(events, f"permission {SID_A}")  # asked again: no new notice, the held one stays
    beat(ctrl, now)
    machine["fullscreen"] = False
    beat(ctrl, now, times=2)
    assert "批准" in ctrl.window.full_text

