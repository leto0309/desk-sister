import json
import sys
import threading
import time
from pathlib import Path

from claude_pet import claude_client
from claude_pet.claude_client import (
    ClaudeCall, build_args, build_message, check_subscription, find_claude, parse_stream, run_claude,
)

FAKE = str(Path(__file__).with_name("fake_claude.py"))
FAKE_CLI = [sys.executable, FAKE]


def test_args_disable_tools_and_customisations():
    args = build_args("claude.exe", "haiku", "SYS")
    assert args[0] == "claude.exe" and "-p" in args
    assert args[args.index("--tools") + 1] == ""
    assert args[args.index("--setting-sources") + 1] == ""
    for flag in ("--safe-mode", "--strict-mcp-config", "--no-session-persistence"):
        assert flag in args
    assert args[args.index("--model") + 1] == "haiku"
    assert args[args.index("--system-prompt") + 1] == "SYS"
    assert not [a for a in args if "dangerous" in a or "bypass" in a.lower()]


def test_message_carries_image_then_text():
    event = json.loads(build_message("看看这个", b"\xff\xd8jpeg"))
    content = event["message"]["content"]
    assert event["type"] == "user" and [b["type"] for b in content] == ["image", "text"]
    assert content[0]["source"]["media_type"] == "image/jpeg"
    assert [b["type"] for b in json.loads(build_message("只有文字"))["message"]["content"]] == ["text"]


def test_parse_stream_success_error_and_partial():
    ok = '{"type":"result","subtype":"success","is_error":false,"result":"happy|嗨"}'
    assert parse_stream("garbage\n" + ok).text == "happy|嗨"
    err = parse_stream('{"type":"result","subtype":"error_during_execution","is_error":true}')
    assert not err.ok and err.error
    partial = '{"type":"assistant","message":{"content":[{"type":"text","text":"talk|半句"}]}}'
    assert parse_stream(partial).text == "talk|半句"
    assert not parse_stream("").ok


def test_paid_backend_settings_never_reach_the_cli(monkeypatch, tmp_path):
    for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL", "CLAUDE_CODE_USE_BEDROCK",
                 "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY", "AWS_BEARER_TOKEN_BEDROCK"):
        monkeypatch.setenv(name, "must-not-leak")
    result = run_claude(build_args(FAKE_CLI, "haiku", "SYS"), build_message("hi", b"img"), timeout=60, cwd=str(tmp_path))
    assert result.ok, result.error
    summary = json.loads(result.text)
    assert summary["kinds"] == ["image", "text"]
    assert summary["visible"] == []
    assert "--safe-mode" in summary["args"]


def test_nonzero_exit_is_failure_even_after_partial_text(monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "fail")
    failed = run_claude(build_args(FAKE_CLI, "haiku", "SYS"), build_message("hi"), timeout=60)
    assert not failed.ok and "boom" in failed.error
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "partial_fail")
    partial = run_claude(build_args(FAKE_CLI, "haiku", "SYS"), build_message("hi"), timeout=60)
    assert not partial.ok and "crashed" in partial.error


def test_timeout_kills_launcher_children_holding_pipes(monkeypatch):
    for mode in ("sleep", "launcher"):
        monkeypatch.setenv("FAKE_CLAUDE_MODE", mode)
        started = time.monotonic()
        result = run_claude(build_args(FAKE_CLI, "haiku", "SYS"), build_message("hi"), timeout=2)
        assert result.timed_out and not result.ok
        assert time.monotonic() - started < 15, mode


def _alive(pid: int) -> bool:
    import subprocess

    out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True).stdout
    return str(pid) in out


def test_timeout_kills_orphaned_descendants(monkeypatch, tmp_path):
    pid_file = tmp_path / "child.pid"
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "orphan")
    monkeypatch.setenv("FAKE_CHILD_PID_FILE", str(pid_file))
    started = time.monotonic()
    result = run_claude(build_args(FAKE_CLI, "haiku", "SYS"), build_message("hi"), timeout=2)
    assert result.timed_out and time.monotonic() - started < 15
    child = int(pid_file.read_text())
    deadline = time.monotonic() + 5
    while _alive(child) and time.monotonic() < deadline:
        time.sleep(0.2)
    assert not _alive(child)


def test_cancel_before_run_sends_nothing(monkeypatch):
    call = ClaudeCall(timeout=60)
    call.cancel()
    monkeypatch.setattr(claude_client, "_spawn", lambda *a, **k: (_ for _ in ()).throw(AssertionError("started")))
    assert call.run(build_args(FAKE_CLI, "haiku", "SYS"), build_message("hi", b"img")).cancelled
    assert call.check_subscription(FAKE_CLI) == (False, "cancelled")


def _cancel_soon(call, delay=1.5):
    timer = threading.Timer(delay, call.cancel)
    timer.start()
    return timer


def test_cancel_during_run_stops_the_process(monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "launcher")
    call = ClaudeCall(timeout=60)
    started = time.monotonic()
    _cancel_soon(call)
    result = call.run(build_args(FAKE_CLI, "haiku", "SYS"), build_message("hi"))
    assert result.cancelled and time.monotonic() - started < 15


def test_cancel_during_subscription_check_stops_it_and_blocks_the_call(monkeypatch):
    monkeypatch.setenv("FAKE_AUTH_MODE", "hang")
    call = ClaudeCall(timeout=60)
    started = time.monotonic()
    _cancel_soon(call)
    assert call.check_subscription(FAKE_CLI) == (False, "cancelled")
    assert time.monotonic() - started < 15
    monkeypatch.setattr(claude_client, "_spawn", lambda *a, **k: (_ for _ in ()).throw(AssertionError("started")))
    assert call.run(build_args(FAKE_CLI, "haiku", "SYS"), build_message("hi")).cancelled


def test_subscription_check(monkeypatch):
    assert check_subscription(FAKE_CLI) == (True, "")
    for status in ('{"loggedIn": false}',
                   '{"loggedIn": true, "authMethod": "api_key", "apiProvider": "firstParty"}',
                   '{"loggedIn": true, "authMethod": "claude.ai", "apiProvider": "bedrock"}',
                   "not json"):
        monkeypatch.setenv("FAKE_AUTH_STATUS", status)
        ok, reason = check_subscription(FAKE_CLI)
        assert not ok and reason, status
    assert not check_subscription(["Z:/definitely/missing/claude.exe"])[0]


def test_run_missing_executable():
    result = run_claude(["Z:/definitely/missing/claude.exe", "-p"], "{}", timeout=5)
    assert not result.ok and "cannot start" in result.error


def test_find_claude_prefers_configured_and_newest_bundle(monkeypatch, tmp_path):
    configured = tmp_path / "my-claude.exe"
    configured.write_text("x")
    assert find_claude(str(configured)) == str(configured)
    assert find_claude(str(tmp_path / "missing.exe")) is None

    monkeypatch.setattr(claude_client.shutil, "which", lambda _name: None)
    monkeypatch.setattr(claude_client.Path, "home", lambda: tmp_path / "home")
    monkeypatch.setenv("APPDATA", str(tmp_path))
    for version in ("2.1.9", "2.1.295", "2.1.30"):
        exe = tmp_path / "Claude" / "claude-code" / version / "abc" / "claude.exe"
        exe.parent.mkdir(parents=True)
        exe.write_text("x")
    assert Path(find_claude()).parts[-3] == "2.1.295"


def test_cancel_returns_at_once_while_process_creation_is_slow(monkeypatch):
    """A slow CreateProcess (e.g. claude on a network share) must not block cancel() on the UI thread."""
    gate = threading.Event()
    real_spawn = claude_client._spawn

    def slow_spawn(args, cwd, cancelled):
        gate.wait(10)
        return real_spawn(args, cwd, cancelled)

    monkeypatch.setattr(claude_client, "_spawn", slow_spawn)
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "sleep")
    call = ClaudeCall(timeout=60)
    results = []
    worker = threading.Thread(target=lambda: results.append(call.run(build_args(FAKE_CLI, "haiku", "SYS"), build_message("hi"))))
    worker.start()
    time.sleep(0.3)
    started = time.monotonic()
    call.cancel()
    assert time.monotonic() - started < 0.5
    gate.set()
    worker.join(15)
    assert not worker.is_alive() and results[0].cancelled


def test_repeated_cancel_and_retry_during_slow_creation_runs_one_creation(monkeypatch):
    gate = threading.Event()
    real_spawn = claude_client._spawn
    spawns = []

    def slow_spawn(args, cwd, cancelled):
        spawns.append(1)
        gate.wait(10)
        return real_spawn(args, cwd, cancelled)

    monkeypatch.setattr(claude_client, "_spawn", slow_spawn)
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "sleep")
    args, message = build_args(FAKE_CLI, "haiku", "SYS"), build_message("hi")
    first = ClaudeCall(timeout=60)
    results = []
    worker = threading.Thread(target=lambda: results.append(first.run(args, message)))
    before = threading.active_count()
    worker.start()
    time.sleep(0.3)
    first.cancel()
    for _ in range(3):  # pause/resume/poke or watchdog-and-tick while creation is still stuck
        retry = ClaudeCall(timeout=60)
        started = time.monotonic()
        result = retry.run(args, message)
        assert result.error == claude_client.LAUNCH_PENDING and time.monotonic() - started < 0.5
        assert retry.check_subscription(FAKE_CLI) == (False, claude_client.LAUNCH_PENDING)
        retry.cancel()
    assert len(spawns) == 1 and threading.active_count() <= before + 1
    gate.set()
    worker.join(15)
    assert results[0].cancelled
    assert run_claude(args.copy(), message, timeout=1).timed_out  # the slot is free again


def test_timeout_holds_when_the_cli_never_reads_a_large_message(monkeypatch, tmp_path):
    pid_file = tmp_path / "child.pid"
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "noread")
    monkeypatch.setenv("FAKE_CHILD_PID_FILE", str(pid_file))
    big = build_message("hi", b"\xff" * (1024 * 1024))  # far larger than any pipe buffer
    started = time.monotonic()
    result = run_claude(build_args(FAKE_CLI, "haiku", "SYS"), big, timeout=2)
    assert result.timed_out and time.monotonic() - started < 15
    child = int(pid_file.read_text())
    deadline = time.monotonic() + 5
    while _alive(child) and time.monotonic() < deadline:
        time.sleep(0.2)
    assert not _alive(child)
