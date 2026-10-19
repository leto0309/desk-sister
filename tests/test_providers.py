import json
import re
import os
import sys
from pathlib import Path

import httpx2
import openai
import pytest

from claude_pet import claude_client, codex_client, openai_client, providers
from claude_pet.claude_client import ClaudeResult
from claude_pet.config import Config
from claude_pet.openai_client import OpenAICompatCall
from claude_pet.providers import PROVIDERS

QtWidgets = pytest.importorskip("PySide6.QtWidgets")
from claude_pet import controller as controller_module  # noqa: E402

SPRITES = Path(__file__).resolve().parents[1] / "assets" / "sprites"
DEEPSEEK = PROVIDERS["deepseek"]
FAKE_SK = "sk-" + "d" * 40  # shaped like an OpenAI / DeepSeek key, not a real one
FAKE_GOOGLE = "AIza" + "g" * 35
REQUEST = httpx2.Request("POST", "https://api.deepseek.com/chat/completions")


# ---- the registry --------------------------------------------------------------------------------
def test_every_provider_is_complete():
    assert set(providers.BACKENDS) == {"subscription", "codex", "api", "openai", "deepseek", "gemini"}
    for provider in PROVIDERS.values():
        assert set(provider.presets) == set(providers.TIERS)
        if provider.paid:
            assert provider.needs_key and provider.key_page.startswith("https://") and provider.company
        if provider.kind == providers.OPENAI_COMPATIBLE:
            assert provider.base_url.startswith("https://")
    assert len({p.vault_entry for p in PROVIDERS.values() if p.needs_key}) == 4  # one vault entry per key


def test_custom_models_override_the_tier_and_are_validated():
    assert providers.model_for(DEEPSEEK, "sonnet") == "deepseek-v4-pro"
    assert providers.model_for(DEEPSEEK, "sonnet", "deepseek-flash") == "deepseek-flash"
    cleaned = providers.clean_custom_models({"deepseek": " deepseek-flash ", "gemini": "bad id!", "nope": "x", "openai": 3})
    assert cleaned == {"deepseek": "deepseek-flash"}
    assert providers.clean_custom_models("junk") == {}
    assert Config(custom_models={"gemini": "models/gemini-3.5-flash"}).normalized().custom_models == {
        "gemini": "models/gemini-3.5-flash"}


# ---- OpenAI-compatible calls -----------------------------------------------------------------------
class Message:
    def __init__(self, content, refusal=None):
        self.content, self.refusal = content, refusal


class Choice:
    def __init__(self, content="talk|你好", finish_reason="stop"):
        self.message, self.finish_reason = Message(content), finish_reason


class Response:
    def __init__(self, choices=None):
        self.choices = [Choice()] if choices is None else choices


class FakeClient:
    def __init__(self, outcome=None, **kwargs):
        self.kwargs, self.outcome, self.sent, self.closed = kwargs, outcome or Response(), [], 0
        outer = self

        class Completions:
            def create(self, **params):
                outer.sent.append(params)
                if isinstance(outer.outcome, BaseException):
                    raise outer.outcome
                return outer.outcome

        self.chat = type("Chat", (), {"completions": Completions()})()

    def close(self):
        self.closed += 1


def factory(outcome=None):
    made = []

    def make(**kwargs):
        made.append(FakeClient(outcome, **kwargs))
        return made[-1]

    return make, made


def status_error(cls, code, message="boom"):
    return cls(message, response=httpx2.Response(code, request=REQUEST), body=None)


@pytest.mark.parametrize("backend, limit", [("openai", "max_completion_tokens"), ("deepseek", "max_tokens"),
                                            ("gemini", "max_tokens")])
def test_each_compatible_provider_gets_its_endpoint_and_limits(backend, limit):
    provider = PROVIDERS[backend]
    make, made = factory()
    result = OpenAICompatCall(provider, 30, load_key=lambda: FAKE_SK, make_client=make).ask("m-1", "SYSTEM", "看", b"jpeg")
    assert result == ClaudeResult(True, text="talk|你好")
    [client] = made
    assert client.kwargs["api_key"] == FAKE_SK and client.kwargs["base_url"] == provider.base_url
    assert client.kwargs["organization"] is None and client.kwargs["max_retries"] == 1
    [params] = client.sent
    assert params["model"] == "m-1" and params[limit] == openai_client.MAX_TOKENS
    system, user = params["messages"]
    assert system == {"role": "system", "content": "SYSTEM"}  # no image outside the user turn
    image, text = user["content"]
    assert image["type"] == "image_url" and image["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert text == {"type": "text", "text": "看"} and client.closed == 1


def test_openai_environment_variables_never_reach_the_client(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-environment-" + "e" * 20)
    monkeypatch.setenv("OPENAI_BASE_URL", "https://evil.example/v1")
    monkeypatch.setenv("OPENAI_ORG_ID", "org-secret")
    monkeypatch.setenv("OPENAI_CUSTOM_HEADERS", "X-Leak: yes")
    real = []

    def make(**kwargs):
        real.append(openai.OpenAI(**kwargs))
        return FakeClient(**kwargs)

    OpenAICompatCall(DEEPSEEK, 30, load_key=lambda: FAKE_SK, make_client=make).ask("deepseek-flash", "S", "hi")
    client = real[0]
    assert client.api_key == FAKE_SK and str(client.base_url).startswith("https://api.deepseek.com")
    assert client.organization is None and "X-Leak" not in client.default_headers
    assert os.environ["OPENAI_ORG_ID"] == "org-secret"  # restored afterwards
    client.close()


@pytest.mark.parametrize("error, expected", [
    (status_error(openai.AuthenticationError, 401), {"bad_api_key": True}),
    (status_error(openai.PermissionDeniedError, 403), {"bad_api_key": True}),
    (status_error(openai.BadRequestError, 400, "Please pass a valid API key"), {"bad_api_key": True}),  # Gemini
    (status_error(openai.BadRequestError, 400, "model not found"), {"error": "DeepSeek API 错误 400：model not found"}),
    (status_error(openai.RateLimitError, 429, "Insufficient Balance"), {"error": "DeepSeek 请求太频繁或额度不足（429）：Insufficient Balance"}),
    (status_error(openai.InternalServerError, 500), {"error": "DeepSeek API 错误 500：boom"}),
    (openai.APITimeoutError(request=REQUEST), {"timed_out": True}),
    (openai.APIConnectionError(request=REQUEST), {"error": "连不上 DeepSeek API：Connection error."}),
])
def test_compatible_errors_become_visible_reasons(error, expected):
    make, _ = factory(error)
    result = OpenAICompatCall(DEEPSEEK, 30, load_key=lambda: FAKE_SK, make_client=make).ask("m", "S", "hi")
    assert not result.ok and not result.cancelled
    for name, value in expected.items():
        assert getattr(result, name) == value


def test_keys_in_error_text_are_hidden_google_ones_too():
    for key in (FAKE_SK, FAKE_GOOGLE):
        leak = status_error(openai.BadRequestError, 400, f"request rejected for {key}")
        make, _ = factory(leak)
        result = OpenAICompatCall(PROVIDERS["gemini"], 30, load_key=lambda k=key: k, make_client=make).ask("m", "S", "hi")
        assert key not in result.error and "[已隐藏]" in result.error


def test_refusals_empty_replies_missing_keys_and_cancel():
    make, _ = factory(Response([Choice(None, "content_filter")]))
    assert OpenAICompatCall(DEEPSEEK, 30, lambda: FAKE_SK, make).ask("m", "S", "hi").error == "模型拒绝了这次请求"
    make, _ = factory(Response([]))
    assert "空回复" in OpenAICompatCall(DEEPSEEK, 30, lambda: FAKE_SK, make).ask("m", "S", "hi").error
    make, made = factory()
    assert OpenAICompatCall(DEEPSEEK, 30, lambda: None, make).ask("m", "S", "hi").no_api_key and not made
    call = OpenAICompatCall(DEEPSEEK, 30, lambda: FAKE_SK, make)
    call.cancel()
    assert call.ask("m", "S", "hi").cancelled and not made


# ---- Codex subscription (a fake codex CLI) --------------------------------------------------------------
FAKE_CODEX = r'''
import json, os, sys
args = sys.argv[1:]
record = os.environ["FAKE_CODEX_RECORD"]
if args[:2] == ["login", "status"]:
    print(os.environ.get("FAKE_CODEX_LOGIN", "Logged in using ChatGPT"))
elif args[:2] == ["features", "list"]:
    print("shell_tool                stable    true")
    print("browser_use               stable    true")
    print("fast_mode                 stable    true")
elif args and args[0] == "exec":
    sys.stdin.reconfigure(encoding="utf-8")  # the real CLI reads UTF-8
    prompt = sys.stdin.read()
    image = args[args.index("-i") + 1] if "-i" in args else ""
    out = args[args.index("-o") + 1]
    with open(record, "w", encoding="utf-8") as f:
        json.dump({"args": args, "cwd": os.getcwd(), "prompt": prompt, "image": image,
                   "image_existed": bool(image) and os.path.exists(image),
                   "api_key": os.environ.get("OPENAI_API_KEY"), "codex_key": os.environ.get("CODEX_API_KEY")}, f)
    with open(out, "w", encoding="utf-8") as f:
        f.write(os.environ.get("FAKE_CODEX_REPLY", "happy|主人好～"))
'''


@pytest.fixture
def fake_codex(tmp_path, monkeypatch):
    """A Python stand-in for the codex binary, started through the real spawn (Job Object and all)."""
    script = tmp_path / "fake_codex.py"
    script.write_text(FAKE_CODEX, encoding="utf-8")
    record = tmp_path / "record.json"
    monkeypatch.setenv("FAKE_CODEX_RECORD", str(record))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-must-not-reach-codex-" + "x" * 20)
    monkeypatch.setenv("CODEX_API_KEY", "must-not-reach-codex")
    real_spawn = claude_client._spawn

    def spawn(args, cwd, cancelled):
        if args and args[0] == "fake-codex":
            args = [sys.executable, str(script), *args[1:]]
        return real_spawn(args, cwd, cancelled)

    monkeypatch.setattr(claude_client, "_spawn", spawn)
    return "fake-codex", record


def test_codex_answers_with_tools_off_and_the_screenshot_gone_afterwards(fake_codex):
    launcher, record = fake_codex
    call = codex_client.CodexCall(60)
    assert call.check_login(launcher) == (True, "")
    result = call.ask(launcher, "", "SYSTEM PROMPT", "看看这个", b"\xff\xd8jpeg")
    assert result == ClaudeResult(True, text="happy|主人好～")
    seen = json.loads(record.read_text(encoding="utf-8"))
    args = seen["args"]
    disabled = {args[i + 1] for i, a in enumerate(args) if a == "--disable"}
    assert disabled == {"shell_tool", "browser_use"}  # risky ones the installed CLI knows; never an unknown name
    for flag in ("--ephemeral", "--ignore-user-config", "--skip-git-repo-check"):
        assert flag in args
    assert args[args.index("-s") + 1] == "read-only" and "-m" not in args and args[-1] == "-"
    assert 'forced_login_method="chatgpt"' in args and "--strict-config" in args
    assert 'model_reasoning_effort="low"' in args
    assert Path(seen["cwd"]).parent == codex_client.TEMP_ROOT  # the test's own temp root, never the real one
    assert seen["image_existed"] and Path(seen["cwd"]) == Path(seen["image"]).parent
    codex_client.wait_cleanup(5)  # deleted in the background
    assert not Path(seen["image"]).exists() and not Path(seen["cwd"]).exists()  # deleted with its folder
    assert "SYSTEM PROMPT" in seen["prompt"] and "看看这个" in seen["prompt"]
    assert seen["api_key"] is None and seen["codex_key"] is None  # only the ChatGPT login is usable


def test_codex_without_a_chatgpt_login_is_refused(fake_codex, monkeypatch):
    launcher, _record = fake_codex
    monkeypatch.setenv("FAKE_CODEX_LOGIN", "Logged in using an API key - sk-***")
    ok, reason = codex_client.CodexCall(60).check_login(launcher)
    assert not ok and "不是 ChatGPT 订阅登录" in reason


def test_codex_custom_model_and_no_screenshot(fake_codex):
    launcher, record = fake_codex
    result = codex_client.CodexCall(60).ask(launcher, "gpt-6-luna", "S", "你好")
    assert result.ok
    args = json.loads(record.read_text(encoding="utf-8"))["args"]
    assert args[args.index("-m") + 1] == "gpt-6-luna" and "-i" not in args


def test_feature_list_parsing():
    out = "shell_tool    stable   true\nbrowser_use   stable   true\n\n  continuation line\n"
    assert codex_client.parse_features(out) == {"shell_tool", "browser_use"}


# ---- the pet --------------------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def pet(app, tmp_path, monkeypatch):
    monkeypatch.setattr(controller_module.capture, "idle_seconds", lambda: 0.0)
    monkeypatch.setattr(controller_module.capture, "is_fullscreen", lambda _i: False)
    monkeypatch.setattr(controller_module.capture, "notification_busy", lambda: False)
    monkeypatch.setattr(claude_client, "find_claude", lambda _configured="": None)
    monkeypatch.setattr(codex_client, "find_codex", lambda _configured="": "codex.exe")
    monkeypatch.setattr(controller_module, "app_data_dir", lambda: tmp_path)
    monkeypatch.setattr(controller_module, "save_config", lambda *_a, **_k: None)
    ctrl = controller_module.PetController(app, Config(dwell_sec=0, paused=True), SPRITES, tmp_path / "config.json")
    vault, asked = {}, []
    ctrl._load_key = lambda entry: vault.get(entry)
    ctrl._save_key = lambda key, entry: vault.__setitem__(entry, key)
    ctrl._delete_key = lambda entry: vault.pop(entry, None) is not None
    ctrl._confirm = lambda title, text: asked.append(text) or True
    ctrl._spawn = lambda fn: fn()
    return ctrl, vault, asked


def test_switching_to_a_paid_provider_names_the_company_and_wants_its_key(pet):
    ctrl, vault, asked = pet
    prompts = []
    ctrl._ask_secret = lambda title, label: prompts.append(label) or (FAKE_SK, True)
    ctrl.set_backend("deepseek")
    assert ctrl.config.backend == "deepseek" and "DeepSeek" in asked[-1] and "按用量收费" in asked[-1]
    assert "DeepSeek" in prompts[-1] and vault == {"Desk Sister: DeepSeek": FAKE_SK}
    assert ctrl.model_actions["haiku"].text() == "快速省钱（deepseek-flash）"
    ctrl.set_backend("gemini")  # another key, kept apart
    assert set(vault) == {"Desk Sister: DeepSeek", "Desk Sister: Gemini"}
    ctrl.clear_api_key("deepseek")
    assert set(vault) == {"Desk Sister: Gemini"}


def test_switching_to_codex_explains_the_temporary_screenshot(pet, monkeypatch):
    ctrl, _vault, asked = pet
    ctrl.set_backend("codex")
    assert ctrl.config.backend == "codex" and "临时文件夹" in asked[-1] and "会重试" in asked[-1] and "立即删除" not in asked[-1]
    ctrl.set_backend("subscription")
    ctrl.codex = None
    monkeypatch.setattr(codex_client, "find_codex", lambda _configured="": None)
    ctrl.set_backend("codex")
    assert ctrl.config.backend == "subscription" and "codex" in ctrl.window.full_text


def test_each_provider_is_asked_with_its_own_model_and_key(pet, monkeypatch):
    ctrl, vault, _asked = pet
    vault["Desk Sister: DeepSeek"] = FAKE_SK
    ctrl.config.backend = "deepseek"
    ctrl.config.model = "sonnet"
    seen = []

    def fake_ask(self, model, system, text, jpeg=None):
        seen.append((self.provider.id, model, self._load_key()))
        return ClaudeResult(True, "happy|DeepSeek 在此～")

    monkeypatch.setattr(openai_client.OpenAICompatCall, "ask", fake_ask)
    ctrl.tick(force=True, user_message="你好")
    assert seen == [("deepseek", "deepseek-v4-pro", FAKE_SK)] and "DeepSeek 在此" in ctrl.window.full_text
    assert ctrl.set_custom_model("deepseek", "deepseek-flash")
    ctrl.tick(force=True, user_message="再说一句")
    assert seen[-1][1] == "deepseek-flash"
    assert not ctrl.set_custom_model("deepseek", "bad id!") and ctrl.config.custom_models == {"deepseek": "deepseek-flash"}


def test_codex_mode_checks_the_login_and_reports_it(pet, monkeypatch):
    ctrl, _vault, _asked = pet
    ctrl.config.backend = "codex"
    calls = []
    monkeypatch.setattr(codex_client.CodexCall, "check_login", lambda self, exe: calls.append(exe) or (False, "不是 ChatGPT 订阅登录"))
    ctrl.tick(force=True, user_message="你好")
    assert calls == ["codex.exe"] and "ChatGPT 订阅" in ctrl.window.full_text
    monkeypatch.setattr(codex_client.CodexCall, "check_login", lambda self, exe: (True, ""))
    monkeypatch.setattr(codex_client.CodexCall, "ask",
                        lambda self, exe, model, system, text, jpeg=None, effort="low": ClaudeResult(True, "happy|借了 Codex 的脑子～"))
    ctrl.tick(force=True, user_message="你好")
    assert "借了 Codex" in ctrl.window.full_text


def test_the_settings_page_lists_every_provider(pet):
    ctrl, vault, _asked = pet
    ctrl._ask_secret = lambda title, label: (FAKE_GOOGLE, True)
    ctrl.open_settings()
    window = ctrl.settings_window
    assert set(window.backend_radios) == set(PROVIDERS)
    window.backend_radios["gemini"].setChecked(True)
    assert ctrl.config.backend == "gemini" and vault["Desk Sister: Gemini"] == FAKE_GOOGLE
    assert "Google" in window.key_status.text() and "已保存" in window.key_status.text()
    assert FAKE_GOOGLE not in window.key_status.text() and window.set_key_button.isEnabled()
    window.custom_model.setText("gemini-3.8-flash")
    window.custom_model.returnPressed.emit()
    assert ctrl.config.custom_models == {"gemini": "gemini-3.8-flash"}
    assert window.model_combo.itemText(0) == "快速省钱（gemini-3.5-flash）"
    window.backend_radios["subscription"].setChecked(True)
    assert not window.set_key_button.isEnabled() and "不需要 API Key" in window.key_status.text()
    window.close()


def test_no_feature_list_means_no_call_and_no_screenshot(fake_codex, monkeypatch, tmp_path):
    launcher, record = fake_codex
    monkeypatch.setattr(codex_client.CodexCall, "features", lambda self, exe, timeout=30: None)
    before = set(codex_client.TEMP_ROOT.glob(codex_client.FOLDER_PREFIX + "*"))
    result = codex_client.CodexCall(60).ask(launcher, "", "S", "hi", b"\xff\xd8jpeg")
    assert not result.ok and "功能清单" in result.error and not record.exists()  # exec never ran
    assert set(codex_client.TEMP_ROOT.glob(codex_client.FOLDER_PREFIX + "*")) == before


def test_a_locked_screenshot_is_retried_until_it_is_gone(tmp_path, monkeypatch):
    folder = tmp_path / (codex_client.FOLDER_PREFIX + "x")
    folder.mkdir()
    (folder / "screen.jpg").write_bytes(b"secret pixels")
    real_delete = codex_client._delete
    locked = [True]
    monkeypatch.setattr(codex_client, "_delete", lambda f: False if locked[0] else real_delete(f))
    monkeypatch.setattr(codex_client.time, "sleep", lambda _s: None)
    assert not codex_client.remove_folder(folder) and folder in codex_client._pending
    assert codex_client.retry_pending() >= 1  # still locked
    locked[0] = False
    assert codex_client.retry_pending() == 0 and not folder.exists()


def test_leftovers_from_a_crash_are_swept_at_start(tmp_path):
    stale = tmp_path / (codex_client.FOLDER_PREFIX + "old")
    stale.mkdir()
    (stale / "screen.jpg").write_bytes(b"x")
    other = tmp_path / "someone-else"
    other.mkdir()
    assert codex_client.sweep_stale(tmp_path, LATER) == 0
    assert not stale.exists() and other.exists()


def test_codex_login_is_checked_before_every_call(pet, monkeypatch):
    ctrl, _vault, _asked = pet
    ctrl.config.backend = "codex"
    logins = iter([(True, ""), (False, "不是 ChatGPT 订阅登录（Logged in using an API key）")])
    checks = []
    monkeypatch.setattr(codex_client.CodexCall, "check_login", lambda self, exe: checks.append(1) or next(logins))
    monkeypatch.setattr(codex_client.CodexCall, "ask",
                        lambda self, exe, model, system, text, jpeg=None, effort="low": ClaudeResult(True, "happy|第一句～"))
    ctrl.tick(force=True, user_message="你好")
    assert "第一句" in ctrl.window.full_text
    ctrl.tick(force=True, user_message="再来")  # switched to an API key meanwhile: refused, not billed
    assert len(checks) == 2 and "ChatGPT 订阅" in ctrl.window.full_text


def test_cleanup_never_reaches_through_a_link(tmp_path):
    import subprocess

    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "screen.jpg"
    sentinel.write_bytes(b"not ours")
    (outside / "keep.txt").write_text("keep", encoding="utf-8")
    root = tmp_path / "temp"
    root.mkdir()
    link = root / (codex_client.FOLDER_PREFIX + "link")
    made = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)], capture_output=True)
    if made.returncode != 0:
        pytest.skip("cannot create a junction here")
    codex_client.sweep_stale(root, LATER)
    assert codex_client.remove_folder(link, waits=(0,)) is False
    assert sentinel.read_bytes() == b"not ours" and (outside / "keep.txt").exists()
    codex_client._pending.pop(link, None)


def test_only_our_files_are_removed(tmp_path):
    folder = tmp_path / (codex_client.FOLDER_PREFIX + "x")
    folder.mkdir()
    (folder / "screen.jpg").write_bytes(b"pixels")
    (folder / "other.txt").write_text("not ours", encoding="utf-8")
    assert codex_client.remove_folder(folder, waits=(0,)) is False  # something else inside: folder kept
    assert not (folder / "screen.jpg").exists() and (folder / "other.txt").exists()
    assert not codex_client.has_pending()  # not retried forever
    codex_client.retry_pending()
    assert (folder / "other.txt").exists()
    folder.rename(tmp_path / "renamed")  # no handle left behind


def test_only_a_native_codex_exe_is_used(tmp_path, monkeypatch):
    launcher = tmp_path / "codex.cmd"
    launcher.write_text("@echo off", encoding="ascii")
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setenv("PATHEXT", ".COM;.EXE;.BAT;.CMD")
    assert codex_client.find_codex() is None  # no native binary next to the launcher: refuse the batch file
    exe = tmp_path / "node_modules" / "@openai" / "codex-win32-x64" / "vendor" / "x86_64" / "bin" / "codex.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"MZ")
    assert codex_client.find_codex() == str(exe)
    assert codex_client.find_codex(str(launcher)) is None


def test_codex_tiers_differ_by_effort(pet, monkeypatch):
    ctrl, _vault, _asked = pet
    ctrl.config.backend = "codex"
    monkeypatch.setattr(codex_client.CodexCall, "check_login", lambda self, exe: (True, ""))
    efforts = []
    monkeypatch.setattr(codex_client.CodexCall, "ask", lambda self, exe, model, system, text, jpeg=None, effort="?":
                        efforts.append(effort) or ClaudeResult(True, "talk|好"))
    for tier in ("haiku", "sonnet"):
        ctrl.config.model = tier
        ctrl.tick(force=True, user_message="你好")
    assert efforts == ["low", "medium"]
    assert providers.model_label(PROVIDERS["codex"], "sonnet") == "更聪明（账号默认模型，中等推理强度）"


def test_a_hard_link_never_empties_a_file_elsewhere(tmp_path):
    outside = tmp_path / "precious.jpg"
    outside.write_bytes(b"family photo")
    folder = tmp_path / (codex_client.FOLDER_PREFIX + "hard")
    folder.mkdir()
    try:
        os.link(outside, folder / "screen.jpg")
    except OSError:
        pytest.skip("hard links not supported here")
    assert codex_client.sweep_stale(tmp_path, LATER) == 0 and not folder.exists()
    assert outside.read_bytes() == b"family photo"


def test_the_native_exe_wins_over_an_earlier_launcher(tmp_path, monkeypatch):
    first, second = tmp_path / "a", tmp_path / "b"
    first.mkdir()
    second.mkdir()
    (first / "codex.cmd").write_text("@echo off", encoding="ascii")
    (second / "codex.exe").write_bytes(b"MZ")
    monkeypatch.setenv("PATH", f"{first}{os.pathsep}{second}")
    monkeypatch.setenv("PATHEXT", ".COM;.EXE;.BAT;.CMD")
    assert Path(codex_client.find_codex()) == second / "codex.exe"


def test_an_unreadable_leftover_never_stops_the_start(tmp_path, monkeypatch):
    folder = tmp_path / (codex_client.FOLDER_PREFIX + "denied")
    folder.mkdir()
    real_lstat = os.lstat

    def denied(path, *args, **kwargs):
        if str(path).startswith(str(folder)):
            raise PermissionError("access denied")
        return real_lstat(path, *args, **kwargs)

    monkeypatch.setattr(codex_client.os, "lstat", denied)
    assert codex_client.sweep_stale(tmp_path, LATER) >= 0  # no exception
    assert folder.exists()  # not inspectable: treated as unsafe and left alone


def test_no_usable_temp_folder_never_stops_the_start(monkeypatch):
    def none_usable():
        raise FileNotFoundError("No usable temporary directory found")

    monkeypatch.setattr(codex_client, "TEMP_ROOT", None)
    monkeypatch.setattr(codex_client.tempfile, "gettempdir", none_usable)
    assert codex_client.sweep_stale() == 0


def test_the_heartbeat_retries_a_locked_screenshot(pet, tmp_path, monkeypatch):
    ctrl, _vault, _asked = pet
    folder = tmp_path / (codex_client.FOLDER_PREFIX + "later")
    folder.mkdir()
    (folder / "screen.jpg").write_bytes(b"pixels")
    with codex_client._pending_lock:
        codex_client._pending[folder] = None
    ctrl._heartbeat()  # schedules the retry in the background
    import time as clock

    deadline = clock.monotonic() + 5
    while (folder.exists() or ctrl._cleanup_running) and clock.monotonic() < deadline:
        clock.sleep(0.01)
    assert not folder.exists() and not codex_client.has_pending()


def test_an_openai_refusal_field_is_a_refusal():
    choice = Choice(None, "stop")
    choice.message = Message(None, refusal="I can't help with that.")
    make, _ = factory(Response([choice]))
    result = OpenAICompatCall(PROVIDERS["openai"], 30, lambda: FAKE_SK, make).ask("m", "S", "hi")
    assert result.error == "模型拒绝了这次请求"


def test_the_heartbeat_never_waits_for_a_hanging_cleanup(pet, monkeypatch):
    import threading
    import time as clock

    ctrl, _vault, _asked = pet
    release, started = threading.Event(), []
    monkeypatch.setattr(codex_client, "has_pending", lambda: True)

    def hang():
        started.append(1)
        release.wait(5)
        return 0

    monkeypatch.setattr(codex_client, "retry_pending", hang)
    begin = clock.monotonic()
    ctrl._heartbeat()
    ctrl._heartbeat()  # a second beat while the first retry still hangs: no second thread
    assert clock.monotonic() - begin < 1.0
    deadline = clock.monotonic() + 2
    while not started and clock.monotonic() < deadline:
        clock.sleep(0.01)
    assert started == [1]
    ctrl.toggle_pause()  # the UI still responds
    assert ctrl.config.paused is False or ctrl.config.paused is True
    release.set()
    deadline = clock.monotonic() + 2
    while ctrl._cleanup_running and clock.monotonic() < deadline:
        clock.sleep(0.01)
    assert not ctrl._cleanup_running


@pytest.mark.skipif(sys.platform != "win32", reason="Windows handles")
def test_a_held_folder_cannot_be_swapped_meanwhile(tmp_path):
    folder = codex_client._make_folder(tmp_path)
    with pytest.raises(OSError):
        folder.path.rename(tmp_path / "moved")  # the race the handle closes: renaming it away to plant a link
    folder.close()
    folder.path.rename(tmp_path / "moved")  # released afterwards


def test_the_screenshot_never_writes_into_an_existing_file(tmp_path):
    outside = tmp_path / "precious.jpg"
    outside.write_bytes(b"family photo")
    folder = codex_client._make_folder(tmp_path)
    try:
        os.link(outside, folder.path / "screen.jpg")  # planted before the screenshot is written
    except OSError:
        folder.close()
        pytest.skip("hard links not supported here")
    with pytest.raises(FileExistsError):
        codex_client._write_new(folder, "screen.jpg", b"secret pixels")
    assert codex_client.remove_folder(folder) and outside.read_bytes() == b"family photo"


def test_start_and_quit_never_wait_for_a_hanging_cleanup(app, tmp_path, monkeypatch):
    import threading
    import time as clock

    release = threading.Event()
    monkeypatch.setattr(codex_client, "sweep_stale", lambda *a, **k: release.wait(5) and 0)
    monkeypatch.setattr(codex_client, "retry_pending", lambda: release.wait(5) and 0)
    monkeypatch.setattr(codex_client, "has_pending", lambda: True)
    monkeypatch.setattr(controller_module, "app_data_dir", lambda: tmp_path)
    monkeypatch.setattr(controller_module, "save_config", lambda *_a, **_k: None)
    begin = clock.monotonic()
    ctrl = controller_module.PetController(app, Config(), SPRITES, tmp_path / "config.json")
    assert clock.monotonic() - begin < 3.0  # the start-up sweep runs in the background
    begin = clock.monotonic()
    ctrl.shutdown()
    assert clock.monotonic() - begin < 3.0  # waits at most about a second
    release.set()


LATER = float("inf")  # sweep folders this test made, as if they were left by an earlier run


def _junction(link, target):
    import subprocess

    made = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True)
    if made.returncode != 0:
        pytest.skip("cannot create a junction here")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows junctions")
def test_a_junction_swapped_above_the_folder_never_redirects_anything(tmp_path):
    ours, theirs, temp = tmp_path / "ours", tmp_path / "theirs", tmp_path / "temp"
    ours.mkdir()
    theirs.mkdir()
    _junction(temp, ours)
    folder = codex_client._make_folder(temp)
    codex_client._write_new(folder, "screen.jpg", b"pixels")
    twin = theirs / folder.path.name  # same name, Same Case or not: only the held handle counts
    twin.mkdir()
    (twin / "screen.jpg").write_bytes(b"not ours")
    (twin / "reply.txt").write_text("their text", encoding="utf-8")
    os.rmdir(temp)
    _junction(temp, theirs)  # the path now leads to their folder
    assert codex_client._read(folder, "reply.txt") is None  # never reads theirs
    assert codex_client.remove_folder(folder)
    assert not (ours / folder.path.name).exists()  # ours is gone
    assert (twin / "screen.jpg").read_bytes() == b"not ours" and (twin / "reply.txt").exists()
    codex_client.retry_pending()
    assert (twin / "screen.jpg").exists() and not codex_client.has_pending()


def test_the_start_up_sweep_leaves_folders_of_this_run_alone(tmp_path):
    current = tmp_path / (codex_client.FOLDER_PREFIX + "now")
    current.mkdir()
    (current / "screen.jpg").write_bytes(b"in use")
    assert codex_client.sweep_stale(tmp_path) == 0 and (current / "screen.jpg").exists()  # a call may be using it
    assert codex_client.sweep_stale(tmp_path, LATER) == 0 and not current.exists()


def test_a_call_never_waits_for_cleanup(fake_codex, monkeypatch):
    import threading
    import time as clock

    launcher, _record = fake_codex
    release = threading.Event()
    real_delete = codex_client._delete
    monkeypatch.setattr(codex_client, "_delete", lambda folder: release.wait(5) and real_delete(folder))
    begin = clock.monotonic()
    result = codex_client.CodexCall(60).ask(launcher, "", "S", "hi", b"\xff\xd8jpeg")
    assert result.ok and clock.monotonic() - begin < 4.0  # the answer comes back while the deletion hangs
    codex_client.schedule_cleanup()
    assert sum(t.name == "codex-cleanup" for t in threading.enumerate()) == 1  # one worker, never more
    release.set()
    codex_client.wait_cleanup(5)
    assert not list(codex_client.TEMP_ROOT.glob(codex_client.FOLDER_PREFIX + "*"))


def test_the_cleanup_worker_keeps_the_root_it_started_with(pet, tmp_path, monkeypatch):
    import threading

    codex_client.wait_cleanup(10)  # the pet's own start-up sweep is done before the test begins
    assert not codex_client.cleanup_running()
    started, release, seen = threading.Event(), threading.Event(), []

    def sweep(root=None, *_args):
        started.set()
        release.wait(5)
        seen.append(root)
        return 0

    monkeypatch.setattr(codex_client, "sweep_stale", sweep)
    first = codex_client.TEMP_ROOT
    codex_client.schedule_cleanup(sweep=True)
    assert started.wait(5)
    monkeypatch.setattr(codex_client, "TEMP_ROOT", tmp_path / "changed-later")
    release.set()
    codex_client.wait_cleanup(5)
    assert seen == [first]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows junctions")
def test_the_cli_is_given_the_real_folder_even_if_a_junction_above_is_swapped(fake_codex, tmp_path, monkeypatch):
    launcher, record = fake_codex
    ours, theirs, temp = tmp_path / "ours", tmp_path / "theirs", tmp_path / "temp"
    ours.mkdir()
    theirs.mkdir()
    _junction(temp, ours)
    monkeypatch.setattr(codex_client, "TEMP_ROOT", temp)
    real_make = codex_client._make_folder
    twins = []

    def make_then_swap(root):
        folder = real_make(root)
        twin = theirs / folder.path.name
        twin.mkdir()
        (twin / "screen.jpg").write_bytes(b"not ours")
        (twin / "reply.txt").write_text("their text", encoding="utf-8")
        twins.append(twin)
        os.rmdir(temp)
        _junction(temp, theirs)  # the path through %TEMP% now leads to their folder
        return folder

    monkeypatch.setattr(codex_client, "_make_folder", make_then_swap)
    result = codex_client.CodexCall(60).ask(launcher, "", "S", "hi", b"\xff\xd8jpeg")
    assert result == ClaudeResult(True, text="happy|主人好～")  # our own reply, not theirs
    seen = json.loads(record.read_text(encoding="utf-8"))
    assert Path(seen["cwd"]).parent == ours.resolve() and Path(seen["image"]).parent == Path(seen["cwd"])
    assert (twins[0] / "screen.jpg").read_bytes() == b"not ours"
    assert (twins[0] / "reply.txt").read_text(encoding="utf-8") == "their text"
    codex_client.wait_cleanup(5)
    assert not list(ours.iterdir())


@pytest.mark.skipif(sys.platform != "win32", reason="Windows ACLs")
def test_the_screenshot_folder_is_private_even_in_a_shared_temp(tmp_path):
    import subprocess

    shared = tmp_path / "shared"
    shared.mkdir()
    subprocess.run(["icacls", str(shared), "/grant", "*S-1-5-32-545:(OI)(CI)R"], capture_output=True, check=True)
    folder = codex_client._make_folder(shared)
    codex_client._write_new(folder, "screen.jpg", b"pixels")
    saved = tmp_path / "acl.txt"
    for item in (folder.path, folder.path / "screen.jpg"):
        subprocess.run(["icacls", str(item), "/save", str(saved)], capture_output=True, check=True)
        sddl = saved.read_bytes().decode("utf-16-le").lstrip("\ufeff").splitlines()[1]
        trustees = {_full_sid(ace.split(";")[-1]) for ace in re.findall(r"\(([^)]*)\)", sddl)}
        assert trustees <= {codex_client._current_user_sid(), "S-1-5-18"}, sddl  # no Users, no Everyone
        assert "D:P" in sddl or item != folder.path  # the folder does not inherit from the shared parent
    assert codex_client.remove_folder(folder)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows handles")
@pytest.mark.parametrize("broken", ["_attributes", "open_osfhandle"])
def test_a_failed_reply_read_never_leaves_a_handle_open(tmp_path, monkeypatch, broken):
    folder = codex_client._make_folder(tmp_path)
    codex_client._write_new(folder, "reply.txt", b"answer")

    def fail(*_args, **_kwargs):
        raise OSError("injected")

    owner = codex_client if broken == "_attributes" else codex_client.msvcrt
    real = getattr(owner, broken)
    monkeypatch.setattr(owner, broken, fail)
    with pytest.raises(OSError):
        codex_client._read(folder, "reply.txt")
    monkeypatch.setattr(owner, broken, real)
    assert codex_client.remove_folder(folder)  # a leaked handle would block deleting the reply


@pytest.mark.skipif(sys.platform != "win32", reason="Windows handles")
def test_a_leftover_in_use_at_start_is_cleaned_once_released(tmp_path):
    old = tmp_path / (codex_client.FOLDER_PREFIX + "busy")
    old.mkdir()
    (old / "screen.jpg").write_bytes(b"pixels")
    blocker = codex_client._check(codex_client._CreateFileW(str(old), 0x1, 0x3, None, 3, 0x02000000, None))
    try:  # another program holds it without sharing delete
        codex_client.sweep_stale(tmp_path, LATER)
        assert old.exists() and codex_client.has_pending()
        codex_client.retry_pending()
        assert old.exists() and codex_client.has_pending()  # still held: kept for later
    finally:
        codex_client._CloseHandle(blocker)
    codex_client.retry_pending()  # no restart needed
    assert not old.exists() and not codex_client.has_pending()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows junctions")
def test_a_rechecked_leftover_never_follows_a_swapped_temp_root(tmp_path):
    ours, theirs, temp = tmp_path / "ours", tmp_path / "theirs", tmp_path / "temp"
    name = codex_client.FOLDER_PREFIX + "busy"
    for base in (ours, theirs):
        (base / name).mkdir(parents=True)
        (base / name / "screen.jpg").write_bytes(b"pixels")
    (theirs / name / "screen.jpg").write_bytes(b"not ours")
    _junction(temp, ours)
    blocker = codex_client._check(codex_client._CreateFileW(str(ours / name), 0x1, 0x3, None, 3, 0x02000000, None))
    try:
        codex_client.sweep_stale(temp, LATER)
        assert codex_client.has_pending()
    finally:
        codex_client._CloseHandle(blocker)
    os.rmdir(temp)
    _junction(temp, theirs)  # the temp root now leads elsewhere
    codex_client.retry_pending()
    assert (theirs / name / "screen.jpg").read_bytes() == b"not ours" and not codex_client.has_pending()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows handles")
def test_the_start_up_sweep_never_replaces_a_folder_a_call_holds(tmp_path):
    folder = codex_client._make_folder(tmp_path)
    codex_client._write_new(folder, "screen.jpg", b"pixels")
    with codex_client._pending_lock:
        codex_client._pending[folder.path] = folder  # a call just finished with it
    codex_client.sweep_stale(tmp_path, LATER)  # finds it busy (we hold it) and must keep our entry
    with codex_client._pending_lock:
        assert codex_client._pending.get(folder.path) is folder
    codex_client.retry_pending()
    assert not folder.path.exists() and not codex_client.has_pending()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows handles")
def test_a_rechecked_leftover_swapped_for_another_folder_is_left_alone(tmp_path):
    root, elsewhere = tmp_path / "temp", tmp_path / "elsewhere"
    name = codex_client.FOLDER_PREFIX + "busy"
    (root / name).mkdir(parents=True)
    (root / name / "screen.jpg").write_bytes(b"pixels")
    (elsewhere / name).mkdir(parents=True)
    (elsewhere / name / "screen.jpg").write_bytes(b"not ours")
    blocker = codex_client._check(codex_client._CreateFileW(str(root / name), 0x1, 0x3, None, 3, 0x02000000, None))
    try:
        codex_client.sweep_stale(root, LATER)
        assert codex_client.has_pending()
    finally:
        codex_client._CloseHandle(blocker)
    (root / name).rename(tmp_path / "moved-away")
    (elsewhere / name).rename(root / name)  # another old plain folder under the same name
    codex_client.retry_pending()
    assert (root / name / "screen.jpg").read_bytes() == b"not ours" and not codex_client.has_pending()


def test_an_unreadable_path_entry_never_stops_the_codex_search(tmp_path, monkeypatch):
    first, second = tmp_path / "denied", tmp_path / "npm"
    first.mkdir()
    exe = second / "node_modules" / "@openai" / "codex-win32-x64" / "vendor" / "x86_64" / "bin" / "codex.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"MZ")
    (second / "codex.cmd").write_text("@echo off", encoding="ascii")
    monkeypatch.setenv("PATH", f"{first}{os.pathsep}{second}")
    monkeypatch.setenv("PATHEXT", ".COM;.EXE;.BAT;.CMD")
    real_is_file = Path.is_file

    def denied(self, *args, **kwargs):
        if str(self).startswith(str(first)):
            raise PermissionError("access denied")
        return real_is_file(self, *args, **kwargs)

    monkeypatch.setattr(Path, "is_file", denied)
    assert codex_client.find_codex() == str(exe)


def test_child_env_never_sees_openai_variables_half_removed(monkeypatch):
    import threading

    from claude_pet import claude_client, openai_client

    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.invalid")
    inside, release, copied = threading.Event(), threading.Event(), []

    def slow_client(**_kwargs):
        inside.set()  # the variables are hidden right now
        release.wait(5)
        return object()

    builder = threading.Thread(target=openai_client.clean_client, args=(slow_client,))
    builder.start()
    assert inside.wait(5)
    reader = threading.Thread(target=lambda: copied.append(claude_client.environ_snapshot()))
    reader.start()
    reader.join(0.3)
    assert reader.is_alive()  # waits for the environment to be whole again
    release.set()
    builder.join(5)
    reader.join(5)
    assert copied and copied[0].get("OPENAI_BASE_URL") == "https://example.invalid"


def test_the_codex_search_never_blocks_the_ui(pet, app, monkeypatch):
    import threading
    import time as clock

    ctrl, _vault, asked = pet
    ctrl._spawn = controller_module.PetController._spawn  # a real background thread
    ctrl.codex = None
    release = threading.Event()
    monkeypatch.setattr(codex_client, "find_codex", lambda _configured="": release.wait(5) and "codex.exe")
    begin = clock.monotonic()
    ctrl.set_backend("codex")
    ctrl.toggle_pause()  # the UI still answers while the search hangs
    assert clock.monotonic() - begin < 1.0 and ctrl.config.backend != "codex"
    release.set()
    deadline = clock.monotonic() + 5
    while ctrl.config.backend != "codex" and clock.monotonic() < deadline:
        app.processEvents()
        clock.sleep(0.01)
    assert ctrl.config.backend == "codex" and ctrl.codex == "codex.exe" and "临时文件夹" in asked[-1]


def _codex_waiting(ctrl, monkeypatch):
    texts, queued = [], []
    ctrl.config.backend, ctrl.codex = "codex", None
    monkeypatch.setattr(codex_client.CodexCall, "check_login", lambda self, exe: (True, ""))
    monkeypatch.setattr(codex_client.CodexCall, "ask", lambda self, exe, model, system, text, jpeg=None, effort="low":
                        texts.append(text) or ClaudeResult(True, "happy|好～"))
    ctrl._spawn = queued.append  # the search waits until the test lets it finish
    return texts, queued


def _finish_search(ctrl, queued):
    ctrl._spawn = lambda fn: fn()
    assert len(queued) == 1  # one search, however many requests
    queued[0]()


def test_a_message_sent_while_codex_is_searched_for_is_sent_once(pet, monkeypatch):
    ctrl, _vault, _asked = pet
    texts, queued = _codex_waiting(ctrl, monkeypatch)
    ctrl.config.paused = False
    ctrl.tick()  # an automatic look starts the search
    ctrl.tick(force=True, user_message="你好呀")
    ctrl.tick()  # another automatic look never replaces the message
    _finish_search(ctrl, queued)
    assert sum("你好呀" in text for text in texts) == 1


@pytest.mark.parametrize("meanwhile", ["pause", "switch"])
def test_a_request_cancelled_during_the_codex_search_is_never_sent(pet, monkeypatch, meanwhile):
    ctrl, _vault, _asked = pet
    texts, queued = _codex_waiting(ctrl, monkeypatch)
    ctrl.config.paused = False
    ctrl.tick(force=True, user_message="还在吗")
    if meanwhile == "pause":
        ctrl.toggle_pause()
    else:
        ctrl.set_backend("subscription")
    _finish_search(ctrl, queued)
    assert texts == [] and ctrl.codex == "codex.exe"  # the search result is still kept



def _full_sid(text: str) -> str:
    """icacls writes well-known accounts as SDDL aliases (SY, or LA when running as the built-in Administrator)."""
    import ctypes
    from ctypes import wintypes

    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    sid, out = ctypes.c_void_p(), wintypes.LPWSTR()
    if not advapi.ConvertStringSidToSidW(text, ctypes.byref(sid)):
        return text
    try:
        advapi.ConvertSidToStringSidW(sid, ctypes.byref(out))
        return out.value
    finally:
        ctypes.windll.kernel32.LocalFree(sid)
