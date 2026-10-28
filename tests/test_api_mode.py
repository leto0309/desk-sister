import os
import sys
import uuid
from pathlib import Path

import anthropic
import httpx2
import pytest

from claude_pet import api_client, claude_client, credstore, i18n
from claude_pet.api_client import API_BASE_URL, API_MODELS, ApiCall, looks_like_key
from claude_pet.config import Config

QtWidgets = pytest.importorskip("PySide6.QtWidgets")
from claude_pet import controller as controller_module  # noqa: E402
from claude_pet.controller import Outcome, error_summary  # noqa: E402

SPRITES = Path(__file__).resolve().parents[1] / "assets" / "sprites"
ANTHROPIC_ENTRY = "Desk Sister: Anthropic"
FAKE_KEY = "sk-ant-api03-" + "x" * 40  # not a real key: shaped like one
REQUEST = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


class Block:
    def __init__(self, type_, text=""):
        self.type, self.text = type_, text


class Response:
    def __init__(self, text="talk|你好", stop_reason="end_turn", blocks=None):
        self.stop_reason = stop_reason
        self.content = blocks if blocks is not None else [Block("thinking"), Block("text", text)]


class FakeClient:
    def __init__(self, outcome=None, **kwargs):
        self.kwargs, self.outcome, self.sent, self.closed = kwargs, outcome or Response(), [], 0
        self.messages = self._Endpoint(self, beta=False)
        self.beta = type("Beta", (), {"messages": self._Endpoint(self, beta=True)})()

    class _Endpoint:
        def __init__(self, client, beta):
            self.client, self.is_beta = client, beta

        def create(self, **params):
            self.client.sent.append((self.is_beta, params))
            if isinstance(self.client.outcome, BaseException):
                raise self.client.outcome
            return self.client.outcome

    def close(self):
        self.closed += 1


def factory(outcome=None):
    made = []

    def make(**kwargs):
        made.append(FakeClient(outcome, **kwargs))
        return made[-1]

    return make, made


def status_error(cls, code):
    return cls("boom", response=httpx2.Response(code, request=REQUEST), body=None)


# ---- the API call ----------------------------------------------------------------------------------
def test_a_request_uses_the_saved_key_a_fixed_host_and_low_effort():
    make, made = factory()
    result = ApiCall(30, load_key=lambda: FAKE_KEY, make_client=make).ask("haiku", "SYSTEM", "看看这个", b"jpeg")
    assert result == claude_client.ClaudeResult(True, text="talk|你好")
    [client] = made
    assert client.kwargs == {"api_key": FAKE_KEY, "base_url": API_BASE_URL, "timeout": 30, "max_retries": 1}
    [(beta, params)] = client.sent
    assert not beta and params["model"] == API_MODELS["haiku"] == "claude-haiku-5-5"
    assert params["system"] == "SYSTEM" and params["output_config"] == {"effort": "low"}
    image, text = params["messages"][0]["content"]
    assert image["type"] == "image" and image["source"]["media_type"] == "image/jpeg" and text["text"] == "看看这个"
    assert client.closed == 1


def test_sonnet_asks_for_the_server_side_fallback():
    make, made = factory()
    ApiCall(30, load_key=lambda: FAKE_KEY, make_client=make).ask("sonnet", "S", "hi")
    [(beta, params)] = made[0].sent
    assert beta and params["model"] == "claude-sonnet-5-5"
    assert params["betas"] == ["server-side-fallback-2026-07-01"] and params["fallbacks"] == "default"
    assert [block["type"] for block in params["messages"][0]["content"]] == ["text"]  # no screenshot


def test_environment_variables_can_neither_swap_the_key_nor_redirect_it(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-from-environment-" + "y" * 20)
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "token-from-environment")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://evil.example")
    real = []

    def make(**kwargs):
        real.append(anthropic.Anthropic(**kwargs))
        return FakeClient(**kwargs)

    ApiCall(30, load_key=lambda: FAKE_KEY, make_client=make).ask("haiku", "S", "hi")
    client = real[0]
    assert client.api_key == FAKE_KEY and client.auth_token is None
    assert str(client.base_url).startswith("https://api.anthropic.com")
    client.close()


@pytest.mark.parametrize("error, expected", [
    (status_error(anthropic.AuthenticationError, 401), {"bad_api_key": True}),
    (status_error(anthropic.PermissionDeniedError, 403), {"bad_api_key": True}),
    (status_error(anthropic.RateLimitError, 429), {"error": "API 请求太频繁（429），稍后再试"}),
    (status_error(anthropic.InternalServerError, 500), {"error": "API 错误 500：boom"}),
    (anthropic.APITimeoutError(request=REQUEST), {"timed_out": True}),
    (anthropic.APIConnectionError(request=REQUEST), {"error": "连不上 Anthropic API：Connection error."}),
])
def test_api_errors_become_visible_reasons(error, expected):
    make, _made = factory(error)
    result = ApiCall(30, load_key=lambda: FAKE_KEY, make_client=make).ask("haiku", "S", "hi")
    assert not result.ok and not result.cancelled
    for name, value in expected.items():
        assert getattr(result, name) == value
    assert FAKE_KEY not in result.error


def test_refusals_empty_replies_and_missing_keys():
    make, _ = factory(Response(stop_reason="refusal", blocks=[]))
    assert ApiCall(30, load_key=lambda: FAKE_KEY, make_client=make).ask("haiku", "S", "hi").error == "模型拒绝了这次请求"
    make, _ = factory(Response(blocks=[Block("thinking")]))
    assert "空回复" in ApiCall(30, load_key=lambda: FAKE_KEY, make_client=make).ask("haiku", "S", "hi").error
    make, made = factory()
    missing = ApiCall(30, load_key=lambda: None, make_client=make).ask("haiku", "S", "hi")
    assert missing.no_api_key and not made  # no client, no request

    def broken():
        raise credstore.CredentialError(5, "denied")

    assert "读取 API Key 失败" in ApiCall(30, load_key=broken, make_client=make).ask("haiku", "S", "hi").error


def test_cancel_before_or_during_a_request_drops_the_reply():
    make, made = factory()
    call = ApiCall(30, load_key=lambda: FAKE_KEY, make_client=make)
    call.cancel()
    assert call.ask("haiku", "S", "hi").cancelled and not made

    class Hanging(FakeClient):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.messages.create = self.create_and_get_cancelled

        def create_and_get_cancelled(self, **_params):
            call.cancel()  # the UI thread cancels while the request is in flight
            raise anthropic.APIConnectionError(request=REQUEST)

    call = ApiCall(30, load_key=lambda: FAKE_KEY, make_client=Hanging)
    result = call.ask("haiku", "S", "hi")
    assert result.cancelled


def test_only_plausible_keys_are_accepted():
    assert looks_like_key(FAKE_KEY)
    for bad in ("", "short", FAKE_KEY + " ", "sk-ant-中文" + "x" * 30, "x" * 600):
        assert not looks_like_key(bad)


def _round_trip(target: str) -> None:
    try:
        assert credstore.load_secret(target) is None
        credstore.save_secret(FAKE_KEY, target)
        assert credstore.load_secret(target) == FAKE_KEY
        credstore.save_secret(FAKE_KEY[::-1], target)  # overwrite
        assert credstore.load_secret(target) == FAKE_KEY[::-1]
    except BaseException:
        credstore.delete_secret(target)  # leave nothing behind, then let it be tried again
        raise
    assert credstore.delete_secret(target)  # the settings say "removed" on this answer
    assert credstore.load_secret(target) is None and not credstore.delete_secret(target)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Credential Manager")
@pytest.mark.skipif(bool(os.environ.get("DESK_SISTER_PARALLEL_RUN")),
                    reason="test runs side by side would make the real Credential Manager lose writes")
def test_credential_manager_round_trip():
    """The real store. Windows keeps a user's credentials together, and another program writing at the same moment
    can put back an older state of them (a write, or a delete, undone); seen under load. So a round trip that came
    out wrong is tried again with a new name, and only one that never comes out right fails."""
    for attempt in range(3):
        try:
            _round_trip(f"DeskSister/test-{uuid.uuid4().hex}")
            return
        except (AssertionError, credstore.CredentialError):
            if attempt == 2:
                raise


def test_a_save_waits_until_the_store_gives_back_the_new_secret():
    """Under load the store once answered with the old key right after the overwrite succeeded."""
    answers = iter(["old", "old", "new"])
    pauses = []
    assert credstore.settle("new", "t", read=lambda _t: next(answers), pause=pauses.append)
    assert len(pauses) == 2
    pauses.clear()
    assert not credstore.settle("new", "t", read=lambda _t: "old", pause=pauses.append)
    assert len(pauses) == credstore.SETTLE_TRIES - 1 and sum(pauses) <= 0.5

    def failing(_t):
        raise credstore.CredentialError(5, "busy")

    assert not credstore.settle("new", "t", read=failing, pause=lambda _s: None)


def test_a_write_the_store_lost_is_made_again_and_never_lost_silently():
    """Under load a write reported as done sometimes never showed up at all: write it again, else say so."""
    store, writes = {}, []

    def lossy_write():  # the first write is lost
        writes.append(1)
        if len(writes) > 1:
            store["t"] = "new"

    credstore._save_checked("new", "t", lossy_write, read=store.get, pause=lambda _s: None)
    assert len(writes) == 2 and store["t"] == "new"
    writes.clear()
    with pytest.raises(credstore.CredentialError):
        credstore._save_checked("new", "t", lambda: writes.append(1), read=lambda _t: None, pause=lambda _s: None)
    assert len(writes) == credstore.WRITE_TRIES


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Credential Manager")
def test_delete_says_whether_there_was_a_key(monkeypatch):
    """Without touching the real store: removed is True, nothing there is False, any other failure is an error."""
    answers = {"there": (True, 0), "gone": (False, credstore._ERROR_NOT_FOUND), "denied": (False, 5)}
    last = []

    def fake_delete(target, _type, _flags):
        ok, error = answers[target]
        last[:] = [error]
        return ok

    monkeypatch.setattr(credstore, "_CredDeleteW", fake_delete)
    monkeypatch.setattr(credstore.ctypes, "get_last_error", lambda: last[0])
    assert credstore.delete_secret("there") is True
    assert credstore.delete_secret("gone") is False
    with pytest.raises(credstore.CredentialError):
        credstore.delete_secret("denied")


def test_a_read_that_keeps_failing_is_named_in_the_error():
    """A store that cannot be read (say, access denied) is reported as such, not only as "save it again"."""
    def denied(_t):
        raise credstore.CredentialError(5, "access denied")

    with pytest.raises(credstore.CredentialError) as raised:
        credstore._save_checked("new", "t", lambda: None, read=denied, pause=lambda _s: None)
    assert "access denied" in str(raised.value) and isinstance(raised.value.__cause__, credstore.CredentialError)
    assert "再保存" not in str(raised.value)  # saving again would not help
    i18n.set_language("en")
    try:
        with pytest.raises(credstore.CredentialError) as raised:
            credstore._save_checked("new", "t", lambda: None, read=denied, pause=lambda _s: None)
    finally:
        i18n.set_language("zh")
    assert str(raised.value) == ("Windows Credential Manager could not be read, so there is no way to confirm the key "
                                 "was stored ([Errno 5] access denied)")


def test_a_busy_moment_is_not_blamed_for_a_write_the_store_lost():
    """One read failing while the store was busy, the rest giving back the old key: the lost write is the cause."""
    answers = iter([credstore.CredentialError(1726, "busy")])

    def busy_once(_t):
        error = next(answers, None)
        if error:
            raise error
        return "old"

    with pytest.raises(credstore.CredentialError) as raised:
        credstore._save_checked("new", "t", lambda: None, read=busy_once, pause=lambda _s: None)
    assert str(raised.value) == "Windows 凭据写入后读不回来，请再保存一次" and raised.value.__cause__ is None


def test_config_backend_is_validated():
    assert Config().backend == "subscription"
    assert Config(backend="api").normalized().backend == "api"
    assert Config(backend="paid?").normalized().backend == "subscription"


# ---- the pet ------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def pet(app, tmp_path, monkeypatch):
    monkeypatch.setattr(controller_module.capture, "idle_seconds", lambda: 0.0)
    monkeypatch.setattr(controller_module.capture, "is_fullscreen", lambda _i: False)
    monkeypatch.setattr(controller_module.capture, "notification_busy", lambda: False)
    monkeypatch.setattr(claude_client, "find_claude", lambda _configured="": None)  # no Claude Code at all
    monkeypatch.setattr(controller_module, "app_data_dir", lambda: tmp_path)
    monkeypatch.setattr(controller_module, "save_config", lambda *_a, **_k: None)
    ctrl = controller_module.PetController(app, Config(dwell_sec=0), SPRITES, tmp_path / "config.json")
    vault = {}
    ctrl._load_key = lambda entry: vault.get(entry)
    ctrl._save_key = lambda key, entry: vault.__setitem__(entry, key)
    ctrl._delete_key = lambda entry: vault.pop(entry, None) is not None
    asked = []
    ctrl._confirm = lambda title, text: asked.append(text) or True
    ctrl._spawn = lambda fn: fn()
    return ctrl, vault, asked


def test_switching_to_api_asks_first_and_wants_a_key(pet):
    ctrl, vault, asked = pet
    ctrl._confirm = lambda title, text: asked.append(text) or False
    ctrl.set_backend("api")
    assert ctrl.config.backend == "subscription"
    assert "按用量收费" in asked[0] and "凭据管理器" in asked[0]
    ctrl._confirm = lambda title, text: True
    ctrl._ask_secret = lambda title, label: ("", False)  # the user cancels the key dialog
    ctrl.set_backend("api")
    assert ctrl.config.backend == "subscription" and not vault
    ctrl._ask_secret = lambda title, label: (f"  {FAKE_KEY}  ", True)
    ctrl.set_backend("api")
    assert ctrl.config.backend == "api" and vault[ANTHROPIC_ENTRY] == FAKE_KEY
    ctrl.set_backend("subscription")
    assert ctrl.config.backend == "subscription" and vault[ANTHROPIC_ENTRY] == FAKE_KEY  # the key stays saved


def test_a_bad_key_is_never_saved_and_clearing_works(pet):
    ctrl, vault, _asked = pet
    ctrl._ask_secret = lambda title, label: ("not a key", True)
    assert not ctrl.set_api_key("api") and not vault and "不像 API Key" in ctrl.window.full_text
    ctrl._ask_secret = lambda title, label: (FAKE_KEY, True)
    assert ctrl.set_api_key("api") and vault[ANTHROPIC_ENTRY] == FAKE_KEY
    ctrl.clear_api_key("api")
    assert not vault and "已经清除" in ctrl.window.full_text


def test_a_store_that_cannot_be_read_is_told_plainly_when_saving_a_key(pet):
    """Her bubble neither says the key was saved nor asks for another try that would not help."""
    ctrl, vault, _asked = pet

    def unreadable(_t):
        raise credstore.CredentialError(5, credstore.tr("读取 Windows 凭据失败"))

    ctrl._save_key = lambda key, entry: credstore._save_checked(key, entry, lambda: None, read=unreadable,
                                                                pause=lambda _s: None)
    ctrl._ask_secret = lambda title, label: (FAKE_KEY, True)
    assert not ctrl.set_api_key("api")
    said = ctrl.window.full_text
    assert said.startswith("没能保存 API Key：") and "没法确认 Key 存好了" in said and "[Errno 5]" in said
    assert "存进去" not in said and "再保存" not in said


def test_api_mode_works_without_claude_code(pet, monkeypatch):
    ctrl, vault, _asked = pet
    vault[ANTHROPIC_ENTRY] = FAKE_KEY
    ctrl.config.backend = "api"
    ctrl.config.paused = True  # no screenshot: answer the chat message only
    sent = []

    def fake_ask(self, model, system, text, jpeg=None):
        sent.append((model, system, text, jpeg, self._load_key()))
        return claude_client.ClaudeResult(True, "happy|用 API 回答你～")

    monkeypatch.setattr(api_client.ApiCall, "ask", fake_ask)
    assert ctrl.claude is None
    ctrl.tick(force=True, user_message="你好")
    [(model, system, text, jpeg, key)] = sent
    assert model == "claude-haiku-5-5" and system == controller_module.persona.system_prompt() and "你好" in text and jpeg is None
    assert key == FAKE_KEY and "用 API 回答你" in ctrl.window.full_text


def test_missing_or_rejected_keys_are_explained(pet):
    ctrl, _vault, _asked = pet
    ctrl.config.backend = "api"
    missing = claude_client.ClaudeResult(False, error="还没有设置 API Key", no_api_key=True)
    ctrl._on_reply(Outcome(ctrl.generation, "reply", result=missing))
    assert "调用方式" in ctrl.window.full_text and "API Key" in error_summary(missing, 120)
    rejected = claude_client.ClaudeResult(False, error="API Key 无效（401）", bad_api_key=True)
    ctrl._on_reply(Outcome(ctrl.generation, "reply", result=rejected))
    assert "被拒绝" in ctrl.window.full_text and ctrl.last_error == "API Key 无效（401）"


def test_subscription_mode_still_needs_claude_code(pet):
    ctrl, _vault, _asked = pet
    ctrl.tick(force=True, user_message="你好")
    assert "找不到 claude" in ctrl.window.full_text


def test_a_key_inside_an_error_message_is_never_passed_on():
    leak = anthropic.BadRequestError(f"invalid x-api-key {FAKE_KEY} (also sk-ant-other-123)",
                                     response=httpx2.Response(400, request=REQUEST), body=None)
    make, _ = factory(leak)
    result = ApiCall(30, load_key=lambda: FAKE_KEY, make_client=make).ask("haiku", "S", "hi")
    assert FAKE_KEY not in result.error and "sk-ant-" not in result.error and "[已隐藏]" in result.error
    assert result.error.startswith("API 错误 400")

    class Leaky(anthropic.APIConnectionError):
        def __str__(self):
            return f"proxy said {FAKE_KEY}"

    make, _ = factory(Leaky(request=REQUEST))
    result = ApiCall(30, load_key=lambda: FAKE_KEY, make_client=make).ask("haiku", "S", "hi")
    assert FAKE_KEY not in result.error and result.error.startswith("连不上 Anthropic API")

