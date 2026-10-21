import json
import random
import time
from pathlib import Path

import pytest
from PIL import Image

from claude_pet import claude_client, persona
from claude_pet.capture import WindowInfo
from claude_pet.config import Config, load_config
from claude_pet.memory import ACTIVITIES, MAX_LOOKS, CompanionMemory, classify_activity

QtWidgets = pytest.importorskip("PySide6.QtWidgets")
from claude_pet import controller as controller_module  # noqa: E402

SPRITES = Path(__file__).resolve().parents[1] / "assets" / "sprites"


# ---- the memory module -------------------------------------------------------------------
def test_activities_are_classified_locally():
    assert classify_activity("Code.exe", "secret.py - Visual Studio Code") == "写代码"
    assert classify_activity("chrome.exe", "【测评】xxx_哔哩哔哩_bilibili") == "看视频"
    assert classify_activity("chrome.exe", "GitHub") == "上网"
    assert classify_activity("WINWORD.EXE", "") == "办公/看文档"
    assert classify_activity("msedge.exe", "合同.pdf") == "办公/看文档"
    assert classify_activity("steam.exe", "") == "打游戏"
    assert classify_activity("WeChat.exe", "") == "聊天"
    assert classify_activity("Spotify.exe", "") == "听音乐"
    assert classify_activity("mspaint.exe", "") == "在电脑前"
    assert classify_activity("", "") == "在电脑前"


def clock(start):
    now = [start]
    return now, lambda: now[0]


def test_time_adds_up_per_day_and_resets_at_midnight(tmp_path):
    day1 = time.mktime((2026, 10, 14, 23, 50, 0, 0, 0, -1))
    now, fn = clock(day1)
    memory = CompanionMemory(tmp_path / "memory.json", now=fn)
    memory.add_time("写代码", 1800)
    memory.add_time("写代码", 1800)
    memory.add_time("看视频", 600)
    memory.add_time("not-an-activity", 999)
    memory.add_time("聊天", -5)
    assert memory.top_today() == ("写代码", 3600)
    assert memory.top_today(7200) is None
    now[0] = day1 + 20 * 60  # 00:10 the next day
    assert memory.top_today() is None and memory.seconds == {}


def test_context_mentions_change_and_today(tmp_path):
    now, fn = clock(time.mktime((2026, 10, 14, 14, 20, 0, 0, 0, -1)))
    memory = CompanionMemory(None, now=fn)
    assert memory.context("写代码") == ""
    memory.record_look("Code.exe", "写代码")
    memory.add_time("写代码", 2.1 * 3600)
    memory.add_time("聊天", 120)  # under 5 minutes: not mentioned
    now[0] += 3600
    text = memory.context("看视频")
    assert "上次（14:20）看到主人在写代码（Code.exe），现在在看视频" in text
    assert "写代码约 2.1 小时" in text and "聊天" not in text
    assert "也在写代码" in memory.context("写代码")
    assert memory.context(None).startswith("今天：")  # current window refused: only the past is used


def test_persistence_round_trip_cap_and_corruption(tmp_path):
    path = tmp_path / "memory.json"
    now, fn = clock(time.time())
    memory = CompanionMemory(path, now=fn)
    for i in range(MAX_LOOKS + 5):
        memory.record_look(f"p{i}.exe", "写代码")
    memory.add_time("看视频", 900)
    memory.flush()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert len(data["looks"]) == MAX_LOOKS and data["looks"][-1]["process"] == f"p{MAX_LOOKS + 4}.exe"
    assert "title" not in json.dumps(data)  # nothing but process names and categories
    again = CompanionMemory(path, now=fn)
    assert again.looks == memory.looks and again.seconds == {"看视频": 900}
    path.write_text("{broken", encoding="utf-8")
    assert CompanionMemory(path, now=fn).looks == []
    path.write_text(json.dumps({"day": again.day, "seconds": {"写代码": "x", "黑客": 5, "看视频": 99999999},
                                "looks": [{"ts": "x"}, {"ts": 1, "process": "a.exe", "activity": "写代码"}]}), encoding="utf-8")
    loaded = CompanionMemory(path, now=fn)
    assert loaded.seconds == {} and loaded.looks == [{"ts": 1.0, "process": "a.exe", "activity": "写代码"}]
    loaded.clear()
    assert json.loads(path.read_text(encoding="utf-8"))["looks"] == []


def test_in_memory_mode_never_writes(tmp_path):
    memory = CompanionMemory(None)
    memory.record_look("Code.exe", "写代码")
    memory.flush()
    memory.clear()
    assert list(tmp_path.iterdir()) == []


def test_prompt_carries_memory_and_settings_validate(tmp_path):
    text = persona.build_user_text("t", "Code.exe", "15:00", [], memory="今天：写代码约 2.0 小时。")
    assert "陪伴记忆：今天：写代码约 2.0 小时。" in text
    assert "陪伴记忆" not in persona.build_user_text("t", "Code.exe", "15:00", [])
    path = tmp_path / "c.json"
    path.write_text(json.dumps({"companion_memory": 0}), encoding="utf-8")
    assert load_config(path).companion_memory is False and Config().companion_memory is True
    assert set(ACTIVITIES) >= {"写代码", "看视频"}


# ---- controller integration ----------------------------------------------------------------
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
    front = {"info": WindowInfo(1, "main.py - Visual Studio Code", "Code.exe", 4242, (0, 0, 800, 600))}
    monkeypatch.setattr(controller_module.capture, "foreground_window", lambda: front["info"])
    monkeypatch.setattr(controller_module.capture, "window_info", lambda _hwnd: front["info"])
    monkeypatch.setattr(controller_module.capture, "capture_window", lambda _i: Image.new("RGB", (800, 600), "white"))
    memory = CompanionMemory(tmp_path / "memory.json")
    ctrl = controller_module.PetController(app, Config(dwell_sec=0), SPRITES, tmp_path / "config.json", memory=memory)
    jobs = []

    def fake_ask(job, snapshot):
        jobs.append(job)
        return claude_client.ClaudeResult(True, "talk|好"), True

    monkeypatch.setattr(ctrl, "_ask_claude", fake_ask)
    ctrl._spawn = lambda fn: fn()
    now = [5000.0]
    ctrl._clock = lambda: now[0]
    ctrl._memory_tick_at = ctrl._memory_flush_at = now[0]
    ctrl.last_external_hwnd = 1
    return ctrl, front, jobs, now, memory


def beat(ctrl, now, seconds=1.0, times=1):
    for _ in range(times):
        now[0] += seconds
        ctrl._heartbeat()


def test_heartbeat_counts_time_only_for_watchable_windows(pet):
    ctrl, front, _jobs, now, memory = pet
    beat(ctrl, now, times=3)
    assert memory.seconds == {"写代码": 3.0}
    beat(ctrl, now, seconds=600)  # a stalled timer counts at most 5 s
    assert memory.seconds["写代码"] == 8.0
    front["info"] = WindowInfo(2, "和朋友的聊天", "WeChat.exe", 4343, (0, 0, 800, 600))  # blocklisted
    beat(ctrl, now, times=3)
    assert "聊天" not in memory.seconds
    ctrl.config.watch_mode, ctrl.config.allowlist = "allowlist", ["steam.exe"]
    front["info"] = WindowInfo(1, "main.py - Visual Studio Code", "Code.exe", 4242, (0, 0, 800, 600))
    beat(ctrl, now, times=2)
    assert memory.seconds["写代码"] == 8.0  # not on the allowlist: not counted
    ctrl.config.watch_mode = "blocklist"
    ctrl.asleep = True  # (a heartbeat would wake her at once: the fake input idle is 0 s)
    now[0] += 2
    ctrl._update_memory()
    assert memory.seconds["写代码"] == 8.0  # asleep: the user is away
    ctrl.asleep = False
    ctrl.config.companion_memory = False
    beat(ctrl, now, times=2)
    assert memory.seconds["写代码"] == 8.0  # switched off


def test_looks_are_recorded_and_the_context_reaches_the_prompt(pet):
    ctrl, front, jobs, now, memory = pet
    memory.add_time("写代码", 7200)
    ctrl.tick(force=True)
    assert memory.looks[-1]["process"] == "Code.exe" and memory.looks[-1]["activity"] == "写代码"
    assert "写代码约 2.0 小时" in jobs[-1].memory_context
    front["info"] = WindowInfo(3, "番剧_哔哩哔哩_bilibili", "msedge.exe", 4444, (0, 0, 800, 600))
    ctrl.last_fingerprint = None
    ctrl.tick(force=True)
    assert "现在在看视频" in jobs[-1].memory_context
    assert memory.looks[-1] == {"ts": memory.looks[-1]["ts"], "process": "msedge.exe", "activity": "看视频"}
    front["info"] = WindowInfo(4, "家人群", "WeChat.exe", 4545, (0, 0, 800, 600))
    ctrl.tick(force=True, user_message="在吗")  # refused window: answered without a picture
    assert memory.looks[-1]["process"] == "msedge.exe"  # nothing recorded about the chat window
    assert "WeChat" not in jobs[-1].memory_context and "聊天" not in jobs[-1].memory_context


def test_memory_is_saved_periodically_and_on_shutdown(pet, tmp_path):
    ctrl, _front, _jobs, now, _memory = pet
    path = tmp_path / "memory.json"
    beat(ctrl, now, times=2)
    assert not path.exists()
    beat(ctrl, now, seconds=5, times=13)  # past the 60 s flush interval
    assert path.exists() and json.loads(path.read_text(encoding="utf-8"))["seconds"]["写代码"] > 0
    ctrl.tick(force=True)
    ctrl.shutdown()
    assert json.loads(path.read_text(encoding="utf-8"))["looks"][-1]["process"] == "Code.exe"


def test_switch_and_clear(pet, tmp_path):
    ctrl, _front, _jobs, now, memory = pet
    memory.record_look("Code.exe", "写代码")
    ctrl.set_companion_memory(False)
    assert not ctrl.config.companion_memory and ctrl._memory_context() == ""
    ctrl.set_companion_memory(True)
    ctrl.clear_companion_memory()
    assert memory.looks == [] and "清空" in ctrl.window.full_text
    assert json.loads((tmp_path / "memory.json").read_text(encoding="utf-8"))["looks"] == []


def test_self_talk_sometimes_mentions_the_main_activity(pet):
    ctrl, _front, _jobs, now, memory = pet
    memory.add_time("写代码", 3 * 3600)
    ctrl._rng = random.Random(0)
    said = set()
    for _ in range(40):
        ctrl.window.clear_bubble()
        ctrl.window.last_said_at = float("-inf")
        assert ctrl.maybe_self_talk()
        said.add(ctrl.window.full_text)
    assert any("「写代码」上已经花了 3.0 小时" in s for s in said)
    assert any("写代码" not in s or "花了" not in s for s in said)  # ordinary lines too



def test_corrupt_timestamps_are_dropped(tmp_path):
    path = tmp_path / "memory.json"
    good = {"ts": 1_760_000_000, "process": "a.exe", "activity": "写代码"}
    raw = ('{"looks": [{"ts": 1e309, "process": "x.exe", "activity": "写代码"}, '
           '{"ts": NaN, "process": "x.exe", "activity": "写代码"}, '
           '{"ts": ' + "9" * 400 + ', "process": "x.exe", "activity": "写代码"}, '
           '{"ts": -5, "process": "x.exe", "activity": "写代码"}, '
           '{"ts": true, "process": "x.exe", "activity": "写代码"}, '
           + json.dumps(good) + '], "day": "x", "seconds": {}}')
    path.write_text(raw, encoding="utf-8")
    memory = CompanionMemory(path)  # must not raise
    assert memory.looks == [{"ts": 1_760_000_000.0, "process": "a.exe", "activity": "写代码"}]
    assert "a.exe" in memory.context("看视频")  # formatting the time works


def test_a_failed_clear_says_so_and_retries(pet, tmp_path, monkeypatch):
    ctrl, _front, _jobs, now, memory = pet
    memory.record_look("Code.exe", "写代码")
    memory.flush()
    import claude_pet.memory as memory_module

    def denied(*_a):
        raise PermissionError("read-only")

    monkeypatch.setattr(memory_module.os, "replace", denied)
    ctrl.clear_companion_memory()
    assert "没能改写" in ctrl.window.full_text and memory.dirty and memory.looks == []
    assert json.loads((tmp_path / "memory.json").read_text(encoding="utf-8"))["looks"]  # disk still old
    monkeypatch.undo()
    memory.flush()  # the next save retries
    assert json.loads((tmp_path / "memory.json").read_text(encoding="utf-8"))["looks"] == []


def test_switching_off_or_clearing_cancels_a_request_holding_the_old_summary(pet):
    ctrl, _front, jobs, now, memory = pet
    memory.add_time("写代码", 7200)
    for action in (ctrl.clear_companion_memory, lambda: ctrl.set_companion_memory(False)):
        ctrl.config.companion_memory = True
        memory.add_time("写代码", 7200)
        pending = []
        ctrl._spawn = pending.append
        ctrl.tick(force=True)  # the job already carries the summary
        call = ctrl.current_call
        action()
        assert call.cancelled and not ctrl.busy
        before = len(jobs)
        pending[0]()  # the old worker runs late
        assert len(jobs) == before  # nothing was sent with the old summary
        looks = list(memory.looks)
        ctrl._spawn = lambda fn: fn()
        assert memory.looks == looks


def test_memory_lines_do_not_repeat_while_the_figure_is_unchanged(pet):
    ctrl, _front, _jobs, now, memory = pet
    memory.add_time("写代码", 3 * 3600)
    ctrl._rng = random.Random(0)
    ctrl._rng.random = lambda: 0.0  # always take the memory branch
    said = []
    for _ in range(6):
        ctrl.window.clear_bubble()
        ctrl.window.last_said_at = float("-inf")
        ctrl.maybe_self_talk()
        said.append(ctrl.window.full_text)
    memory_lines = [s for s in said if "花了" in s]
    assert len(memory_lines) == 1  # said once, then ordinary lines while it is still recent



def test_corrupt_daily_seconds_are_dropped_without_failing(tmp_path):
    path = tmp_path / "memory.json"
    today = CompanionMemory(None).day
    raw = ('{"day": "' + today + '", "looks": [], "seconds": {"写代码": ' + "9" * 400 +
           ', "看视频": 1e309, "聊天": NaN, "上网": 600}}')
    path.write_text(raw, encoding="utf-8")
    memory = CompanionMemory(path)  # must not raise
    assert memory.seconds == {"上网": 600.0}


def test_ai_assistants_are_their_own_activity():
    assert classify_activity("claude.exe", "Claude") == "和 AI 一起干活"
    assert classify_activity("ChatGPT.exe", "") == "和 AI 一起干活"
    assert classify_activity("chrome.exe", "Claude - Google Chrome") == "和 AI 一起干活"
    assert classify_activity("msedge.exe", "DeepSeek - 探索未至之境") == "和 AI 一起干活"
    assert classify_activity("msedge.exe", "豆包 - 字节跳动") == "和 AI 一起干活"
    # Keeps priority: coding tools, videos about AI, documents, ordinary browsing.
    assert classify_activity("Code.exe", "claude-pet - Visual Studio Code") == "写代码"
    assert classify_activity("chrome.exe", "ChatGPT 教程_哔哩哔哩_bilibili") == "看视频"
    assert classify_activity("chrome.exe", "Claude 论文.pdf") == "办公/看文档"
    assert classify_activity("chrome.exe", "天气预报 - Google Chrome") == "上网"


def test_the_new_activity_is_remembered(tmp_path):
    memory = CompanionMemory(tmp_path / "memory.json")
    memory.record_look("claude.exe", "和 AI 一起干活")
    memory.add_time("和 AI 一起干活", 2 * 3600)
    memory.flush()
    loaded = CompanionMemory(tmp_path / "memory.json")
    assert loaded.looks[-1]["activity"] == "和 AI 一起干活" and loaded.top_today() == ("和 AI 一起干活", 7200)
    assert "和 AI 一起干活约 2.0 小时" in loaded.context("看视频")

