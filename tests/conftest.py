import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _private_codex_temp(tmp_path_factory, monkeypatch):
    """No test may touch the real %TEMP% Codex folders (a running pet may be using one)."""
    from claude_pet import codex_client

    monkeypatch.setattr(codex_client, "TEMP_ROOT", tmp_path_factory.mktemp("codex-temp"))
    yield
    import threading

    for thread in threading.enumerate():  # let cleanup workers finish before TEMP_ROOT is restored
        if thread.name == "codex-cleanup":
            thread.join(timeout=10)



@pytest.fixture(autouse=True)
def _no_update_checks(monkeypatch):
    """No test may reach GitHub: the update check is told it is offline unless a test says otherwise."""
    from claude_pet import updates

    def offline(opener=None):
        if opener is not None:
            return real(opener)
        return None

    real = updates.fetch_latest
    monkeypatch.setattr(updates, "fetch_latest", offline)
    real_asset = updates.fetch_asset
    monkeypatch.setattr(updates, "fetch_asset", lambda opener=None, name=updates.ASSET_NAME:
                        None if opener is None else real_asset(opener, name=name))
    monkeypatch.setattr(updates, "launch_restart", lambda _env: pytest.fail("no test may start the update helper"))


@pytest.fixture(autouse=True)
def _chinese_by_default():
    """Tests speak Chinese unless they switch; whatever a test switched to is undone after it."""
    from claude_pet import i18n

    real = i18n.system_language
    def chinese_system():  # a pet made with the default config follows "the system": Chinese here
        return "zh"

    chinese_system.__wrapped__ = real  # for the test of the real detection
    i18n.system_language = chinese_system
    i18n.set_language("zh")
    yield
    i18n.system_language = real
    i18n.set_language("zh")



@pytest.fixture(autouse=True)
def _silent(monkeypatch):
    """No test makes a sound: her voice player plays nothing."""
    from claude_pet import voice

    monkeypatch.setattr(voice, "_winsound_play", lambda path: None)
