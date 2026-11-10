"""The cyclic garbage collector runs on the GUI thread only (see claude_pet/main_gc.py)."""
import gc
import threading
import weakref
from pathlib import Path

import pytest

QtWidgets = pytest.importorskip("PySide6.QtWidgets")
from claude_pet import main_gc  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


class Node:
    def __init__(self):
        self.me = self  # a cycle: only the collector can free it


def litter(count: int) -> weakref.ref:
    nodes = [Node() for _ in range(count)]
    return weakref.ref(nodes[0])


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def collector(app):
    """Made with the automatic collector on, as in the app; the test run's own setting comes back afterwards."""
    before = gc.isenabled()
    gc.collect()
    gc.enable()
    now = [1000.0]
    made = main_gc.MainThreadCollector(clock=lambda: now[0])
    made._timer.stop()  # the tests call check() themselves
    try:
        yield made, now
    finally:
        made.stop()
        (gc.enable if before else gc.disable)()


def test_it_switches_the_automatic_collector_off_and_stop_brings_it_back(collector):
    made, _now = collector
    assert not gc.isenabled()
    made.stop()
    assert gc.isenabled()


def test_a_worker_thread_no_longer_collects_and_the_gui_thread_does(collector):
    made, _now = collector
    where = []

    def seen(phase, _info):
        if phase == "start":
            where.append(threading.current_thread())

    probe = []
    gc.callbacks.append(seen)
    try:
        worker = threading.Thread(target=lambda: probe.append(litter(5000)))
        worker.start()
        worker.join(10)
        assert not where and probe[0]() is not None  # far past the threshold, and nothing was collected there
        assert made.check() is not None
        assert where == [threading.main_thread()] and probe[0]() is None
    finally:
        gc.callbacks.remove(seen)


def test_nothing_is_collected_below_the_threshold(collector):
    made, _now = collector
    gc.collect()
    probe = litter(5)
    assert made.check() is None and probe() is not None


def test_the_oldest_generation_past_its_threshold_is_the_one_collected(collector, monkeypatch):
    made, _now = collector
    monkeypatch.setattr(gc, "get_threshold", lambda: (700, 10, 10))
    done = []
    monkeypatch.setattr(gc, "collect", lambda generation=2: done.append(generation))
    for counts, expected in (((701, 0, 0), 0), ((701, 11, 0), 1), ((701, 11, 11), 2), ((701, 3, 11), 2),
                             ((700, 11, 11), None)):
        monkeypatch.setattr(gc, "get_count", lambda counts=counts: counts)
        assert made.check() == expected, counts
    assert done == [0, 1, 2, 2]
    monkeypatch.setattr(gc, "get_threshold", lambda: (0, 10, 10))  # 0 first: the collector is switched off
    monkeypatch.setattr(gc, "get_count", lambda: (5000, 50, 50))
    assert made.check() is None
    monkeypatch.setattr(gc, "get_threshold", lambda: (700, 0, 10))  # 0 later: whenever that count is above 0
    for counts, expected in (((701, 1, 0), 1), ((701, 0, 0), 0), ((701, 1, 11), 2)):
        monkeypatch.setattr(gc, "get_count", lambda counts=counts: counts)
        assert made.check() == expected, counts



def test_a_cycle_that_became_garbage_in_the_middle_generation_goes_when_its_threshold_is_0(collector):
    """Codex's review: with gc.set_threshold(700, 0, 10) a cycle promoted to the middle generation was left for the
    five-minute full collection, because a later threshold of 0 was read as "never"."""
    made, _now = collector
    before = gc.get_threshold()
    gc.collect()
    gc.set_threshold(700, 0, 10)
    try:
        holder = [Node()]
        probe = weakref.ref(holder[0])
        gc.collect(0)  # it survives the youngest collection: now in the middle generation
        assert gc.get_count()[1] >= 1
        holder.clear()  # and only now becomes garbage
        keep = [[] for _ in range(1000)]  # the youngest count goes past its threshold (kept alive: not garbage)
        assert gc.get_count()[0] > 700 and probe() is not None
        assert made.check() == 1 and probe() is None
        del keep
    finally:
        gc.set_threshold(*before)

def test_a_full_collection_every_few_minutes_whatever_the_counters_say(collector):
    made, now = collector
    gc.collect()
    assert made.check() is None
    now[0] += main_gc.FULL_EVERY_SEC
    probe = litter(5)
    assert made.check() == 2 and probe() is None
    assert made.check() is None  # and the next one is a full interval away
    now[0] += main_gc.FULL_EVERY_SEC - 1
    assert made.check() is None


def test_its_timer_runs_on_the_gui_thread_and_calls_check(app):
    from PySide6.QtTest import QTest

    before = gc.isenabled()
    made = main_gc.MainThreadCollector(interval_ms=1)
    try:
        assert made._timer.isActive() and made._timer.interval() == 1 and made.thread() is app.thread()
        calls = []
        made._due = lambda: calls.append(threading.current_thread())  # nothing is due: check() returns None
        for _ in range(500):  # up to 5 s: a busy machine may deliver a 1 ms timer late (seen in a full run)
            if len(calls) >= 3:
                break
            QTest.qWait(10)
        assert len(calls) >= 3 and set(calls) == {threading.main_thread()}
    finally:
        made.stop()
        (gc.enable if before else gc.disable)()


def test_the_app_installs_it_before_the_pet_and_its_worker_threads_exist():
    source = (ROOT / "app.py").read_text(encoding="utf-8")
    assert source.count("MainThreadCollector(app)") == 1
    assert source.index("MainThreadCollector(app)") < source.index("PetController(app")
