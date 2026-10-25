import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


_FAKE_OFFSET = 0.0  # seconds the faked wall clock is ahead of the real one


def _fake_wall_clock() -> None:
    """DESK_SISTER_FAKE_NOW=2027-02-06T15:56 runs the tests as if it were then (the clock keeps ticking from there).

    The pet reads the wall clock only through time.time, time.localtime and time.strftime; devtools/run_tests_at_times.py
    uses this to run the whole suite at the hours and days that change what she says."""
    when = os.environ.get("DESK_SISTER_FAKE_NOW")
    if not when:
        return
    global _FAKE_OFFSET
    target = time.mktime(time.strptime(when, "%Y-%m-%dT%H:%M"))
    offset = _FAKE_OFFSET = target - time.time()
    real_time, real_localtime, real_strftime = time.time, time.localtime, time.strftime

    def fake_time() -> float:
        return real_time() + offset

    def fake_localtime(secs=None):
        return real_localtime(fake_time() if secs is None else secs)

    def fake_strftime(fmt, t=None):
        return real_strftime(fmt, fake_localtime() if t is None else t)

    time.time, time.localtime, time.strftime = fake_time, fake_localtime, fake_strftime


_fake_wall_clock()  # before any test imports the pet, so defaults like `now=time.time` take the fake clock


def _seeded_randomness() -> None:
    """DESK_SISTER_SEED=7 makes every random choice repeatable: the module functions and every random.Random()
    made without a seed (hers included). Runs with many seeds find tests that pass only on a lucky draw."""
    seed = os.environ.get("DESK_SISTER_SEED")
    if not seed:
        return
    import itertools
    import random

    random.seed(int(seed))
    serial = itertools.count(int(seed) * 100_000)
    unseeded = random.Random

    class Seeded(unseeded):
        def __init__(self, x=None):
            super().__init__(next(serial) if x is None else x)

    random.Random = Seeded


_seeded_randomness()


@pytest.fixture(autouse=True, scope="session")
def _files_keep_real_time():
    """Files are stamped by the real clock: the one place that compares the two (the start-up sweep of Codex
    folders) keeps its start time on the real clock too."""
    if _FAKE_OFFSET:
        from claude_pet import codex_client

        codex_client._STARTED -= _FAKE_OFFSET
    yield




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
