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
