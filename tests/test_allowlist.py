import json
from pathlib import Path

import pytest
from PIL import Image

from claude_pet import claude_client
from claude_pet.capture import WindowInfo, matches_allowlist
from claude_pet.config import Config, load_config

QtWidgets = pytest.importorskip("PySide6.QtWidgets")
from claude_pet import controller as controller_module  # noqa: E402

SPRITES = Path(__file__).resolve().parents[1] / "assets" / "sprites"


def test_rules_match_process_names_with_wildcards_and_titles_only_with_a_prefix():
    rules = ["Code.exe", "*bilibili*", "title:*Jupyter*"]
    assert matches_allowlist(rules, "code.exe", "secret.docx - VS Code")  # case-insensitive
    assert matches_allowlist(rules, "BiliBili.exe", "")  # wildcard on the process name
    assert matches_allowlist(rules, "chrome.exe", "Untitled - Jupyter Notebook")  # explicit title rule
    assert not matches_allowlist(["*jupyter*"], "chrome.exe", "Jupyter")  # plain rules never read titles
    assert not matches_allowlist(rules, "WeChat.exe", "Code.exe")  # a title that looks like a program
    assert not matches_allowlist([], "code.exe", "")
    assert not matches_allowlist(["", "  ", "title:", 3], "code.exe", "x")
    assert not matches_allowlist(rules, "", "")


def test_allowlist_settings_are_validated(tmp_path):
    path = tmp_path / "c.json"
    for raw, expected in (({"watch_mode": "everything"}, ("blocklist", [])),
                          ({"watch_mode": "allowlist", "allowlist": {"x": 1}}, ("allowlist", [])),
                          ({"watch_mode": "allowlist", "allowlist": [" code.exe ", ""]}, ("allowlist", ["code.exe"]))):
        path.write_text(json.dumps(raw), encoding="utf-8")
        config = load_config(path)
        assert (config.watch_mode, config.allowlist) == expected, raw
    assert (Config().watch_mode, Config().allowlist) == ("blocklist", [])


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def setup(app, tmp_path, monkeypatch):
    for name, value in (("idle_seconds", lambda: 0.0), ("is_fullscreen", lambda _i: False),
                        ("notification_busy", lambda: False)):
        monkeypatch.setattr(controller_module.capture, name, value)
    monkeypatch.setattr(claude_client, "find_claude", lambda _configured="": "claude.exe")
    saved = []
    monkeypatch.setattr(controller_module, "save_config", lambda config, *_a: saved.append(list(config.allowlist)))
    front = {"info": WindowInfo(1, "main.py - Visual Studio Code", "Code.exe", 4242, (0, 0, 800, 600))}
    monkeypatch.setattr(controller_module.capture, "foreground_window", lambda: front["info"])
    monkeypatch.setattr(controller_module.capture, "window_info", lambda _hwnd: front["info"])
    captured = []

    def capture(info):
        captured.append(info.process_name)
        return Image.new("RGB", (800, 600), "white")

    monkeypatch.setattr(controller_module.capture, "capture_window", capture)

    def make(**config):
        ctrl = controller_module.PetController(app, Config(dwell_sec=0, **config), SPRITES, tmp_path / "config.json")
        calls = []

        def fake_ask(job, snapshot):
            calls.append((snapshot.jpeg is not None, job.user_message))
            return claude_client.ClaudeResult(True, "talk|好"), True

        monkeypatch.setattr(ctrl, "_ask_claude", fake_ask)
        ctrl._spawn = lambda fn: fn()
        return ctrl, calls

    return make, front, captured, saved


def test_allowlist_mode_only_looks_at_listed_programs_even_when_poked(setup):
    make, front, captured, _saved = setup
    ctrl, calls = make(watch_mode="allowlist", allowlist=["code.exe"])
    ctrl.tick(force=True)
    assert captured == ["Code.exe"] and calls == [(True, None)]
    front["info"] = WindowInfo(2, "家庭相册", "PhotosApp.exe", 4343, (0, 0, 800, 600))
    ctrl.tick(force=True)  # a poke on an unlisted program
    assert captured == ["Code.exe"] and len(calls) == 1
    assert "不在白名单" in ctrl.window.full_text


def test_the_blocklist_still_applies_inside_the_allowlist(setup):
    make, front, captured, _saved = setup
    ctrl, calls = make(watch_mode="allowlist", allowlist=["msedge.exe"])
    front["info"] = WindowInfo(3, "招商银行 - Edge", "msedge.exe", 4444, (0, 0, 800, 600))
    ctrl.tick(force=True)
    assert captured == [] and calls == [] and "私密" in ctrl.window.full_text


def test_blocklist_mode_ignores_the_allowlist(setup):
    make, front, captured, _saved = setup
    ctrl, calls = make(watch_mode="blocklist", allowlist=["something-else.exe"])
    ctrl.tick(force=True)
    assert captured == ["Code.exe"] and len(calls) == 1


def test_chat_is_answered_without_a_picture_when_the_window_is_refused(setup):
    make, front, captured, _saved = setup
    ctrl, calls = make()
    front["info"] = WindowInfo(4, "和朋友的聊天", "WeChat.exe", 4545, (0, 0, 800, 600))
    ctrl.tick(force=True, user_message="今天好累")
    assert captured == [] and calls == [(False, "今天好累")]  # answered, no screenshot
    ctrl2, calls2 = make(watch_mode="allowlist", allowlist=[])
    front["info"] = WindowInfo(5, "notes", "Notepad.exe", 4646, (0, 0, 800, 600))
    ctrl2.tick(force=True, user_message="你好")
    assert captured == [] and calls2 == [(False, "你好")]


def test_menu_switches_mode_and_adds_or_removes_the_current_program(setup):
    make, front, _captured, saved = setup
    ctrl, _calls = make()
    ctrl.last_external_hwnd = 1
    menu = ctrl.tray.contextMenu()
    menu.aboutToShow.emit()
    assert ctrl.allowlist_action.text() == "把「Code.exe」加入白名单" and ctrl.allowlist_action.isEnabled()
    ctrl.allowlist_action.trigger()
    assert ctrl.config.allowlist == ["Code.exe"] and saved[-1] == ["Code.exe"]
    assert "切到「只看白名单」后生效" in ctrl.window.full_text
    assert ctrl.allowlist_action.text() == "从白名单移除「Code.exe」"
    ctrl.watch_mode_actions["allowlist"].trigger()
    assert ctrl.config.watch_mode == "allowlist" and ctrl.watch_mode_actions["allowlist"].isChecked()
    assert not ctrl.watch_mode_actions["blocklist"].isChecked()
    ctrl.allowlist_action.trigger()  # remove again
    assert ctrl.config.allowlist == []
    ctrl.watch_mode_actions["allowlist"].trigger()
    assert "白名单还是空的" in ctrl.window.full_text
    ctrl.config.allowlist = ["code*"]
    menu.aboutToShow.emit()
    assert "已被白名单规则匹配" in ctrl.allowlist_action.text() and not ctrl.allowlist_action.isEnabled()
    ctrl.last_external_hwnd = 0
    menu.aboutToShow.emit()
    assert not ctrl.allowlist_action.isEnabled()
    ctrl.watch_mode_actions["blocklist"].trigger()
    assert ctrl.config.watch_mode == "blocklist"



def test_menu_entries_are_literal_even_with_brackets(setup):
    from claude_pet.capture import literal_rule

    make, front, captured, _saved = setup
    assert literal_rule("Editor[1].exe") == "Editor[[]1].exe"
    assert matches_allowlist([literal_rule("Editor[1].exe")], "editor[1].exe", "")
    assert not matches_allowlist([literal_rule("Editor[1].exe")], "Editor1.exe", "")
    ctrl, calls = make(watch_mode="allowlist")
    front["info"] = WindowInfo(7, "draft", "Editor[1].exe", 4747, (0, 0, 800, 600))
    ctrl.last_external_hwnd = 7
    ctrl.toggle_current_in_allowlist()
    assert ctrl.config.allowlist == ["Editor[[]1].exe"]
    ctrl.tray.contextMenu().aboutToShow.emit()
    assert ctrl.allowlist_action.text() == "从白名单移除「Editor[1].exe」"
    ctrl.tick(force=True)
    assert captured == ["Editor[1].exe"]
    front["info"] = WindowInfo(8, "other", "Editor1.exe", 4848, (0, 0, 800, 600))
    ctrl.tick(force=True)
    assert captured == ["Editor[1].exe"]  # the look-alike is not allowed
    front["info"] = WindowInfo(7, "draft", "Editor[1].exe", 4747, (0, 0, 800, 600))
    ctrl.toggle_current_in_allowlist()
    assert ctrl.config.allowlist == []


def test_removing_an_entry_tells_when_a_wildcard_still_matches(setup):
    make, front, _captured, _saved = setup
    ctrl, _calls = make(watch_mode="allowlist", allowlist=["Code.exe", "code*"])
    ctrl.last_external_hwnd = 1
    ctrl.toggle_current_in_allowlist()
    assert ctrl.config.allowlist == ["code*"]
    assert "code*" in ctrl.window.full_text and "仍然匹配" in ctrl.window.full_text


def test_tightening_the_scope_cancels_a_running_job(setup, monkeypatch):
    make, front, captured, _saved = setup
    for start_mode, allowlist, tighten in (("blocklist", [], "mode"), ("allowlist", ["Code.exe"], "remove")):
        ctrl, calls = make(watch_mode=start_mode, allowlist=list(allowlist))
        ctrl.last_external_hwnd = 1
        pending = []
        ctrl._spawn = pending.append
        ctrl.tick(force=True)  # job created under the looser rules, worker not run yet
        job_call = ctrl.current_call
        if tighten == "mode":
            ctrl.set_watch_mode("allowlist")
        else:
            ctrl.toggle_current_in_allowlist()
        assert job_call.cancelled and not ctrl.busy
        before = list(captured)
        pending[0]()  # the old worker runs now
        assert captured == before and calls == []  # nothing captured or sent under the old rules



def test_removal_reports_title_rules_that_still_match(setup):
    make, front, captured, _saved = setup
    ctrl, _calls = make(watch_mode="allowlist", allowlist=["Code.exe", "title:*visual studio*"])
    ctrl.last_external_hwnd = 1
    ctrl.toggle_current_in_allowlist()
    assert ctrl.config.allowlist == ["title:*visual studio*"]
    assert "title:*visual studio*" in ctrl.window.full_text and "仍然匹配" in ctrl.window.full_text
    ctrl.tray.contextMenu().aboutToShow.emit()
    assert "已被白名单规则匹配" in ctrl.allowlist_action.text()
    ctrl.tick(force=True)
    assert captured == ["Code.exe"]  # and indeed it is still allowed, as she said
