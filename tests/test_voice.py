"""Her Animalese voice: synthesised babble in step with her typing, only when chosen and never while asleep."""
import array
import io
import random
import wave
from pathlib import Path

import pytest

from claude_pet import claude_client, voice
from claude_pet.config import Config

QtWidgets = pytest.importorskip("PySide6.QtWidgets")
from claude_pet import controller as controller_module  # noqa: E402

SPRITES = Path(__file__).resolve().parents[1] / "assets" / "sprites"


def samples(data):
    with wave.open(io.BytesIO(data)) as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (1, 2, voice.RATE)
        frames = w.readframes(w.getnframes())
    return [int.from_bytes(frames[i:i + 2], "little", signed=True) for i in range(0, len(frames), 2)]


def test_a_line_is_one_blip_per_character_in_step_with_the_typing():
    data = voice.render("主人好", "talk", "squeaky", 60, 35)
    pcm = samples(data)
    slot = int(voice.RATE * 0.035)
    assert len(pcm) == slot * 3 + max(int(voice.RATE * 0.03), min(int(voice.RATE * 0.09), int(slot * 0.9)))
    for i in range(3):
        assert any(abs(v) > 100 for v in pcm[i * slot:i * slot + slot // 2]), i  # each character speaks


def test_the_same_line_always_sounds_the_same_and_moods_differ():
    assert voice.render("你好呀", "happy") == voice.render("你好呀", "happy")
    assert voice.render("你好呀", "happy") != voice.render("你好呀", "sad")
    assert voice.render("你好呀", "talk", "squeaky") != voice.render("你好呀", "talk", "low")


def test_punctuation_and_spaces_are_pauses():
    slot = int(voice.RATE * 0.035)
    pcm = samples(voice.render("啊，  啊", "talk", char_ms=35))
    assert all(v == 0 for v in pcm[3 * slot + slot // 2:4 * slot])  # the comma and spaces are silent once the blip fades
    assert voice.render("。。。", "talk") == b"" and voice.render("   ", "talk") == b""


@pytest.mark.parametrize("mood", ["sleep", "nonsense"])
def test_no_voice_for_sleep_or_an_unknown_mood(mood):
    assert voice.render("Zzz", mood) == b""


def test_volume():
    assert voice.render("啦啦", volume=0) == b""  # nothing to play at all
    loud = max(abs(v) for v in samples(voice.render("啦啦", volume=100)))
    quiet = max(abs(v) for v in samples(voice.render("啦啦", volume=30)))
    assert 0 < quiet < loud <= 32767


def test_english_is_voiced_too():
    assert samples(voice.render("Hello there", "talk", char_ms=18))


# ---- the player -------------------------------------------------------------------------------------------
class Deferred:
    def __init__(self):
        self.jobs = []

    def __call__(self, fn):
        self.jobs.append(fn)


def now():
    return lambda: 0.0


def test_the_player_plays_the_newest_line_only(tmp_path):
    played = []
    player = voice.Player(tmp_path, play=played.append, clock=now())
    later = Deferred()
    player.say("第一句", "talk", "squeaky", 60, 35, spawn=later)
    player.say("第二句", "talk", "squeaky", 60, 35, spawn=later)
    later.jobs[0]()
    assert played == [None, None]  # each new line silences the last; the first was superseded before it was ready
    later.jobs[1]()
    path = played[-1]
    assert played[:-1] == [None, None] and path.parent == tmp_path and samples(path.read_bytes())
    assert sorted(p.name for p in tmp_path.iterdir()) == [path.name]  # the superseded line left no file


def test_a_new_line_cuts_the_one_already_playing(tmp_path):
    played = []
    player = voice.Player(tmp_path, play=played.append, clock=now())
    player.say("第一句", "talk", "squeaky", 60, 35, spawn=lambda fn: fn())
    later = Deferred()
    player.say("第二句", "talk", "squeaky", 60, 35, spawn=later)
    assert played[-1] is None and later.jobs  # stopped before the second line is even made


def test_stop_cuts_a_line_still_being_made(tmp_path):
    played = []
    player = voice.Player(tmp_path, play=played.append, clock=now())
    later = Deferred()
    player.say("还没说完", "talk", "squeaky", 60, 35, spawn=later)
    player.stop()
    later.jobs[0]()
    assert played == [None, None]  # only the stops
    assert list(tmp_path.iterdir()) == []


def test_only_the_latest_file_is_kept(tmp_path):
    (tmp_path / "voice-7.wav").write_bytes(b"old")  # from last time
    played = []
    player = voice.Player(tmp_path, play=played.append, clock=now())
    assert list(tmp_path.iterdir()) == []
    for _ in range(3):
        player.say("嗯", "talk", "squeaky", 60, 35, spawn=lambda fn: fn())
    assert [p.name for p in played if p] == ["voice-1.wav", "voice-2.wav", "voice-3.wav"]
    assert [p.name for p in tmp_path.iterdir()] == ["voice-3.wav"]


class Clock:
    """Stands in for time.monotonic: moves only when told to, e.g. by a slow write."""

    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def test_a_late_line_starts_where_the_typing_is(tmp_path):
    played = []
    clock = Clock()
    player = voice.Player(tmp_path, play=played.append, clock=clock)
    later = Deferred()
    player.say("一二三四五六", "talk", "squeaky", 60, 35, spawn=later)
    clock.t = 0.140  # made 140 ms after the typing began: four characters at 35 ms
    later.jobs[0]()
    full = samples(voice.render("一二三四五六", "talk", "squeaky", 60, 35))
    assert samples(played[-1].read_bytes()) == full[int(voice.RATE * 0.140):]


def test_a_line_made_too_late_is_not_played(tmp_path):
    played = []
    clock = Clock()
    player = voice.Player(tmp_path, play=played.append, clock=clock)
    later = Deferred()
    player.say("短句", "talk", "squeaky", 60, 35, spawn=later)
    clock.t = 5.0
    later.jobs[0]()
    assert played == [None] and list(tmp_path.iterdir()) == []


def test_a_slow_write_is_made_up_for_too(tmp_path, monkeypatch):
    played = []
    clock = Clock()
    writes = []

    def slow_once(path, data):
        path.write_bytes(data)
        writes.append(len(data))
        if len(writes) == 1:
            clock.t += 0.070  # two characters behind after the first write

    monkeypatch.setattr(voice, "_write", slow_once)
    player = voice.Player(tmp_path, play=played.append, clock=clock)
    player.say("一二三四五六", "talk", "squeaky", 60, 35, spawn=lambda fn: fn())
    full = samples(voice.render("一二三四五六", "talk", "squeaky", 60, 35))
    assert len(writes) == 2 and samples(played[-1].read_bytes()) == full[int(voice.RATE * 0.070):]


def test_a_write_so_slow_the_line_is_over_is_not_played(tmp_path, monkeypatch):
    played = []
    clock = Clock()

    def very_slow(path, data):
        path.write_bytes(data)
        clock.t += 0.5

    monkeypatch.setattr(voice, "_write", very_slow)
    player = voice.Player(tmp_path, play=played.append, clock=clock)
    player.say("短句", "talk", "squeaky", 60, 35, spawn=lambda fn: fn())
    assert played == [None] and list(tmp_path.iterdir()) == []


def test_a_failed_write_leaves_no_file(tmp_path, monkeypatch):
    def disk_full(path, data):
        path.write_bytes(data[:100])
        raise OSError("disk full")

    monkeypatch.setattr(voice, "_write", disk_full)
    played = []
    player = voice.Player(tmp_path, play=played.append, clock=now())
    player.say("写不下", "talk", "squeaky", 60, 35, spawn=lambda fn: fn())
    assert played == [None] and list(tmp_path.iterdir()) == []


def test_a_slow_disk_never_holds_up_stop(tmp_path, monkeypatch):
    import threading

    writing, release = threading.Event(), threading.Event()

    def slow_write(path, data):
        writing.set()
        release.wait(5)
        path.write_bytes(data)

    monkeypatch.setattr(voice, "_write", slow_write)
    played = []
    player = voice.Player(tmp_path, play=played.append, clock=now())
    workers = []

    def spawn(fn):
        workers.append(threading.Thread(target=fn, daemon=True))
        workers[-1].start()

    player.say("慢慢写", "talk", "squeaky", 60, 35, spawn=spawn)  # a real worker thread
    assert writing.wait(5)
    stopped = threading.Event()
    threading.Thread(target=lambda: (player.stop(), stopped.set()), daemon=True).start()
    assert stopped.wait(1)  # stop() returned while the file was still being written
    release.set()
    workers[0].join(5)
    assert played == [None, None] and list(tmp_path.iterdir()) == []  # the old line never played


# ---- little sounds ---------------------------------------------------------------------------------------
@pytest.mark.parametrize("name", voice.EFFECTS)
def test_each_effect_is_short_audible_and_follows_the_style(name):
    pcm = voice.effect_pcm(name, "squeaky", 60)
    seconds = len(pcm) / 2 / voice.RATE
    assert 0.1 < seconds < 1.5 and max(abs(v) for v in array.array("h", pcm)) > 1000
    if name != "land":  # (the bump is the same for everyone; its tick and the others follow her pitch)
        assert voice.effect_pcm(name, "low", 60) != pcm
    assert voice.effect_pcm(name, "squeaky", 0) == b"" and voice.effect_pcm("nonsense") == b""


def test_effects_are_softer_than_her_voice_at_the_same_volume():
    loudest = max(abs(v) for v in array.array("h", voice._pcm("啦啦啦", "talk", "squeaky", 100, 35)))
    for name in voice.EFFECTS:
        assert max(abs(v) for v in array.array("h", voice.effect_pcm(name, "squeaky", 100))) <= loudest


def test_mixing_adds_and_keeps_the_longer():
    a = array.array("h", [1000, 2000, 30000]).tobytes()
    b = array.array("h", [10, 20000]).tobytes()
    assert array.array("h", voice._mix(a, b)).tolist() == [1010, 22000, 30000]
    assert array.array("h", voice._mix(b, a)).tolist() == [1010, 22000, 30000]


def test_an_effect_plays_on_its_own(tmp_path):
    played = []
    player = voice.Player(tmp_path, play=played.append, clock=now())
    player.effect("pat", "squeaky", 60, spawn=lambda fn: fn())
    assert samples(played[-1].read_bytes()) == array.array("h", voice.effect_pcm("pat", "squeaky", 60)).tolist()


def test_a_line_right_after_an_effect_carries_it_on(tmp_path):
    played = []
    clock = Clock()
    player = voice.Player(tmp_path, play=played.append, clock=clock)
    player.effect("pat", "squeaky", 60, spawn=lambda fn: fn())
    clock.t = 0.05  # she answers 50 ms into the chirp
    later = Deferred()
    player.say("嘿嘿", "happy", "squeaky", 60, 35, spawn=later)
    assert played[-1] is None  # the chirp file stops for the line...
    later.jobs[0]()
    line = voice._pcm("嘿嘿", "happy", "squeaky", 60, 35)
    rest = voice.effect_pcm("pat", "squeaky", 60)[int(0.05 * voice.RATE) * 2:]
    assert samples(played[-1].read_bytes()) == array.array("h", voice._mix(line, rest)).tolist()  # ...and goes on in it


def test_a_stopped_effect_does_not_come_back_with_the_next_line(tmp_path):
    played = []
    player = voice.Player(tmp_path, play=played.append, clock=now())
    player.effect("snore", "squeaky", 60, spawn=lambda fn: fn())
    player.stop()
    player.say("醒啦", "happy", "squeaky", 60, 35, spawn=lambda fn: fn())
    assert samples(played[-1].read_bytes()) == array.array("h", voice._pcm("醒啦", "happy", "squeaky", 60, 35)).tolist()


def test_an_effect_mid_line_keeps_the_rest_of_the_line(tmp_path):
    played = []
    clock = Clock()
    player = voice.Player(tmp_path, play=played.append, clock=clock)
    player.say("一二三四五六七八", "talk", "squeaky", 60, 35, spawn=lambda fn: fn())
    clock.t = 0.1  # picked up while she talks
    player.effect("lift", "squeaky", 60, spawn=lambda fn: fn())
    line = voice._pcm("一二三四五六七八", "talk", "squeaky", 60, 35)
    rest = line[int(0.1 * voice.RATE) * 2:]
    assert samples(played[-1].read_bytes()) == array.array("h", voice._mix(voice.effect_pcm("lift", "squeaky", 60), rest)).tolist()


def test_an_effect_while_the_line_is_still_being_made_keeps_it_too(tmp_path):
    played = []
    clock = Clock()
    player = voice.Player(tmp_path, play=played.append, clock=clock)
    later = Deferred()
    player.say("一二三四五六", "talk", "squeaky", 60, 35, spawn=later)
    player.effect("pat", "squeaky", 60, spawn=lambda fn: fn())
    later.jobs[0]()  # superseded: the effect's sound already holds the line
    line = voice._pcm("一二三四五六", "talk", "squeaky", 60, 35)
    assert samples(played[-1].read_bytes()) == array.array("h", voice._mix(voice.effect_pcm("pat", "squeaky", 60), line)).tolist()
    assert len([p for p in played if p]) == 1


def test_after_stop_an_effect_is_only_itself(tmp_path):
    played = []
    player = voice.Player(tmp_path, play=played.append, clock=now())
    player.say("还在说", "talk", "squeaky", 60, 35, spawn=lambda fn: fn())
    player.stop()  # the bubble went
    player.effect("land", "squeaky", 60, spawn=lambda fn: fn())
    assert samples(played[-1].read_bytes()) == array.array("h", voice.effect_pcm("land", "squeaky", 60)).tolist()


def test_a_line_long_after_an_effect_is_just_the_line(tmp_path):
    played = []
    clock = Clock()
    player = voice.Player(tmp_path, play=played.append, clock=clock)
    player.effect("lift", "squeaky", 60, spawn=lambda fn: fn())
    clock.t = 30.0
    later = Deferred()
    player.say("嗯", "talk", "squeaky", 60, 35, spawn=later)
    clock.t = 30.0
    later.jobs[0]()
    assert samples(played[-1].read_bytes()) == array.array("h", voice._pcm("嗯", "talk", "squeaky", 60, 35)).tolist()


# ---- the pet ---------------------------------------------------------------------------------------------
class FakeVoice:
    def __init__(self):
        self.said, self.stops, self.effects = [], 0, []

    def say(self, text, mood, style, volume, char_ms):
        self.said.append((text, mood, style, volume, char_ms))

    def effect(self, name, style, volume):
        self.effects.append((name, style, volume))

    def stop(self):
        self.stops += 1


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
    monkeypatch.setattr(controller_module, "app_data_dir", lambda: tmp_path)
    ctrl = controller_module.PetController(app, Config(greeted_on="2099-01-01"), SPRITES, tmp_path / "config.json")
    ctrl._rng = random.Random(1)
    fake = FakeVoice()
    ctrl.window.hushed.disconnect(ctrl.voice.stop)
    ctrl.voice = fake
    ctrl.window.hushed.connect(fake.stop)
    yield ctrl, fake
    if ctrl.settings_window is not None:
        ctrl.settings_window.close()


def test_silent_unless_chosen(pet):
    ctrl, fake = pet
    ctrl.window.say("talk", "主人好")
    assert fake.said == []
    ctrl.set_voice(True)
    ctrl.window.say("happy", "落地成功！")
    assert fake.said == [("落地成功！", "happy", "claude", 60, ctrl.window._typer.interval())]


def test_never_while_asleep_or_muted(pet):
    ctrl, fake = pet
    ctrl.set_voice(True)
    ctrl.window.say("sleep", "Zzz")
    ctrl.asleep = True
    ctrl.window.say("talk", "梦话")
    ctrl.asleep = False
    ctrl.quiet = True
    ctrl.window.say("talk", "全屏中")
    assert fake.said == [] and fake.stops >= 3


def test_the_voice_stops_with_the_bubble_and_when_switched_off(pet):
    ctrl, fake = pet
    ctrl.set_voice(True)
    ctrl.window.say("talk", "说着呢")
    stops = fake.stops
    ctrl.window.clear_bubble()
    assert fake.stops == stops + 1
    ctrl.set_voice(False)
    assert fake.stops == stops + 2


def test_preview_and_choices(pet):
    ctrl, fake = pet
    ctrl.set_voice_style("low")
    ctrl.set_voice_style("nonsense")
    ctrl.set_voice_volume(150)
    ctrl.preview_voice()  # works while her voice is off
    assert ctrl.config.voice_style == "low" and ctrl.config.voice_volume == 100
    assert fake.said[-1][1:4] == ("happy", "low", 100)


@pytest.mark.parametrize("state", ["asleep", "quiet", "quit_pending"])
def test_no_preview_while_hushed(pet, state):
    ctrl, fake = pet
    setattr(ctrl, state, True)
    ctrl.preview_voice()
    assert fake.said == [] and fake.stops >= 1


@pytest.mark.parametrize("bad", [[], {"a": 1}, 3])
def test_a_broken_voice_style_keeps_the_rest_of_the_settings(tmp_path, bad):
    import json

    from claude_pet.config import load_config

    path = tmp_path / "config.json"
    path.write_text(json.dumps({"watch_mode": "allowlist", "voice": True, "voice_style": bad}), encoding="utf-8")
    config = load_config(path)
    assert (config.watch_mode, config.voice, config.voice_style) == ("allowlist", True, "")  # her own


def test_config_cleans_voice_fields():
    config = Config(voice="yes", voice_style="opera", voice_volume=500).normalized()
    assert (config.voice, config.voice_style, config.voice_volume) == (False, "", 100)
    assert Config(voice_volume=True).normalized().voice_volume == 60


def test_settings_row(pet):
    ctrl, fake = pet
    ctrl.open_settings()
    window = ctrl.settings_window
    assert not window.voice_box.isChecked() and window.voice_combo.currentData() == ""
    window.voice_box.setChecked(True)
    window.voice_combo.setCurrentIndex(window.voice_combo.findData("soft"))
    assert ctrl.config.voice and ctrl.config.voice_style == "soft"
    window.voice_volume.setValue(25)
    window.voice_volume.triggerAction(QtWidgets.QAbstractSlider.SliderAction.SliderSingleStepAdd)
    assert ctrl.config.voice_volume == 26


def test_a_file_that_cannot_be_removed_is_left_alone(tmp_path, monkeypatch):
    (tmp_path / "voice-1.wav").write_bytes(b"old")

    def locked(self, missing_ok=False):
        raise PermissionError("in use")

    monkeypatch.setattr(Path, "unlink", locked)
    played = []
    player = voice.Player(tmp_path, play=played.append, clock=now())
    for _ in range(2):
        player.say("嗯", "talk", "squeaky", 60, 35, spawn=lambda fn: fn())
    assert played[-1].name == "voice-2.wav"


def test_a_short_write_past_the_end_of_the_line_is_not_played(tmp_path, monkeypatch):
    clock = Clock()
    pcm = samples(voice.render("短句", "talk", "squeaky", 60, 35))
    end = max(i for i, v in enumerate(pcm) if v) / voice.RATE  # the last audible sample
    writes = []

    def a_little_slow(path, data):
        path.write_bytes(data)
        writes.append(path)
        clock.t = end + 0.001  # well under a character, but past the end of the line

    monkeypatch.setattr(voice, "_write", a_little_slow)
    played = []
    player = voice.Player(tmp_path, play=played.append, clock=clock)
    later = Deferred()
    player.say("短句", "talk", "squeaky", 60, 35, spawn=later)
    clock.t = end - 0.01
    later.jobs[0]()
    assert len(writes) == 1 and played == [None] and list(tmp_path.iterdir()) == []


def test_a_line_that_fails_to_play_leaves_no_file(tmp_path):
    def play(path):
        if path is not None:
            raise RuntimeError("no sound device")

    player = voice.Player(tmp_path, play=play, clock=now())
    player.say("没声卡", "talk", "squeaky", 60, 35, spawn=lambda fn: fn())
    assert list(tmp_path.iterdir()) == [] and player._current is None


def test_stop_after_playing_removes_the_last_file(tmp_path):
    played = []
    player = voice.Player(tmp_path, play=played.append, clock=now(), spawn=lambda fn: fn())
    player.say("说完了", "talk", "squeaky", 60, 35)
    assert len(list(tmp_path.iterdir())) == 1
    player.stop()
    assert list(tmp_path.iterdir()) == [] and played[-1] is None


def test_a_line_still_behind_after_rewriting_is_dropped(tmp_path, monkeypatch):
    clock = Clock()
    writes = []

    def always_slow(path, data):
        path.write_bytes(data)
        writes.append(path)
        clock.t += 0.070  # two characters each time

    monkeypatch.setattr(voice, "_write", always_slow)
    played = []
    player = voice.Player(tmp_path, play=played.append, clock=clock)
    player.say("一二三四五六七八", "talk", "squeaky", 60, 35, spawn=lambda fn: fn())
    assert len(writes) == 2 and played == [None] and list(tmp_path.iterdir()) == []


def test_little_sounds_for_what_happens_to_her(pet):
    ctrl, fake = pet
    ctrl.window.lifted.emit()
    ctrl._on_patted()
    ctrl._on_landed()
    assert fake.effects == []  # her voice is off: so are the sounds
    ctrl.set_voice(True)
    ctrl.set_voice_style("low")
    ctrl.window.lifted.emit()
    ctrl._on_patted()
    ctrl._on_patted()  # every pat sounds, though she answers only now and then
    ctrl._on_landed()
    assert [name for name, *_ in fake.effects] == ["lift", "pat", "pat", "land"]
    assert fake.effects[0][1:] == ("low", 60)


def test_a_snore_once_as_she_dozes_off(pet, monkeypatch):
    ctrl, fake = pet
    ctrl.set_voice(True)
    monkeypatch.setattr(controller_module.capture, "idle_seconds", lambda: 10_000.0)
    ctrl._update_sleep()
    ctrl._update_sleep()
    assert ctrl.asleep and [name for name, *_ in fake.effects] == ["snore"]


def test_no_sounds_in_full_screen_quiet(pet, monkeypatch):
    ctrl, fake = pet
    ctrl.set_voice(True)
    monkeypatch.setattr(controller_module, "full_screen_now", lambda _h=0: True)
    ctrl._update_quiet()
    ctrl._on_patted()
    ctrl._on_landed()
    ctrl.window.lifted.emit()
    monkeypatch.setattr(controller_module.capture, "idle_seconds", lambda: 10_000.0)
    ctrl._update_sleep()
    assert fake.effects == []


def test_the_window_tells_when_she_is_picked_up(app):
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent

    from claude_pet.pet_window import PetWindow

    window = PetWindow(SPRITES, 220)
    lifts = []
    window.lifted.connect(lambda: lifts.append(1))
    window.show()
    at = QPointF(window.width() / 2, window.height() - 100)
    glob = QPointF(window.mapToGlobal(at.toPoint()))

    def event(kind, where, buttons):
        return QMouseEvent(kind, at, where, Qt.MouseButton.LeftButton, buttons, Qt.KeyboardModifier.NoModifier)

    window.mousePressEvent(event(QEvent.Type.MouseButtonPress, glob, Qt.MouseButton.LeftButton))
    for dx in (2, 30, 60):
        window.mouseMoveEvent(event(QEvent.Type.MouseMove, glob + QPointF(dx, 0), Qt.MouseButton.LeftButton))
    window.mouseReleaseEvent(event(QEvent.Type.MouseButtonRelease, glob, Qt.MouseButton.NoButton))
    assert lifts == [1]  # once per pick-up, not per move (and not for a plain click)
    window.close()


# ---- each girl her own voice ------------------------------------------------------------------------------
def test_every_girl_has_her_own_voice():
    from claude_pet import characters

    assert set(voice.GIRL_VOICES) == set(characters.CHARACTERS)
    tones = [voice.tone(girl) for girl in characters.CHARACTERS]
    for i, (base, bright) in enumerate(tones):
        assert 200 <= base <= 800 and 0.6 <= bright <= 1.5
        for other_base, other_bright in tones[i + 1:]:  # heard apart, not just numbers apart: a word's own
            ratio = max(base, other_base) / min(base, other_base)  # pitch already moves by ±14%
            assert ratio >= 1.17 or abs(bright - other_bright) >= 0.2, (base, other_base)
    assert voice.tone("claude") == voice.STYLES["squeaky"]  # Claude keeps the voice she always had
    assert voice.render("你好呀", "talk", "gpt") != voice.render("你好呀", "talk", "deepseek")
    assert voice.effect_pcm("pat", "gemini") != voice.effect_pcm("pat", "glm")
    assert voice.CHOICES[0] == ""


def test_an_unknown_voice_falls_back_alike_for_words_and_sounds():
    assert voice.tone("nobody") == voice.STYLES[voice.DEFAULT_STYLE]
    assert voice.render("你好", "talk", "nobody") == voice.render("你好", "talk", voice.DEFAULT_STYLE)
    assert voice.effect_pcm("pat", "nobody") == voice.effect_pcm("pat", voice.DEFAULT_STYLE)


def test_by_default_each_girl_speaks_in_her_own_voice_until_one_is_chosen(pet):
    ctrl, fake = pet
    ctrl.set_voice(True)
    ctrl.set_character("gpt")
    assert fake.said[-1][2] == "gpt"  # her hello on arriving, in her voice
    ctrl.window.lifted.emit()
    assert fake.effects[-1][1] == "gpt"
    ctrl.set_voice_style("soft")  # one style for every girl
    ctrl.set_character("qwen")
    assert fake.said[-1][2] == "soft"
    ctrl.set_voice_style("")  # back to their own
    ctrl.set_character("deepseek")
    assert fake.said[-1][2] == "deepseek" and ctrl.config.voice_style == ""


def test_the_preview_says_her_own_first_hello_in_her_own_voice(pet):
    from claude_pet import persona

    ctrl, fake = pet
    ctrl.set_character("glm")
    ctrl.set_address("老板")
    ctrl.preview_voice()
    mood, text = persona.girl_lines("glm").ZH["HELLO_LINES"][0]
    assert fake.said[-1][:3] == (text.replace("主人", "老板"), mood, "glm")


@pytest.mark.parametrize(("saved", "expected"), [
    ({"voice_style": "squeaky"}, ""),  # the old default, never really chosen: now her own
    ({"voice_style": "low"}, "low"),  # a real choice stays
    ({"voice_style": "squeaky", "config_version": 2}, "squeaky"),  # chosen since: stays
    ({"voice_style": "squeaky", "config_version": 99}, "squeaky"),  # from a newer version: stays
    ({}, ""),
])
def test_an_older_settings_file_moves_to_her_own_voice(tmp_path, saved, expected):
    import json

    from claude_pet.config import CONFIG_VERSION, load_config, save_config

    path = tmp_path / "config.json"
    path.write_text(json.dumps({"voice": True, **saved}), encoding="utf-8")
    config = load_config(path)
    assert config.voice_style == expected and config.voice
    save_config(config, path)
    again = load_config(path)
    assert again.voice_style == expected and again.config_version == max(saved.get("config_version", 0), CONFIG_VERSION)


def test_a_chosen_squeaky_survives_a_restart(tmp_path):
    from claude_pet.config import load_config, save_config

    path = tmp_path / "config.json"
    save_config(Config(voice_style="squeaky"), path)
    assert load_config(path).voice_style == "squeaky"

@pytest.mark.parametrize(("written", "kept"), [(99, 99), ("x", 2), (True, 2), (1, 2)])
def test_the_settings_version_is_never_lowered(tmp_path, written, kept):
    import json

    from claude_pet.config import load_config

    path = tmp_path / "config.json"
    path.write_text(json.dumps({"config_version": written}), encoding="utf-8")
    assert load_config(path).config_version == kept


def test_settings_switch_back_to_her_own_voice(pet):
    ctrl, fake = pet
    ctrl.open_settings()
    window = ctrl.settings_window
    window.voice_combo.setCurrentIndex(window.voice_combo.findData("soft"))
    assert ctrl.config.voice_style == "soft"
    window.voice_combo.setCurrentIndex(window.voice_combo.findData(""))
    assert ctrl.config.voice_style == "" and window.voice_combo.currentIndex() == 0
    ctrl.set_voice_style("bright")
    window.refresh()
    assert window.voice_combo.currentData() == "bright"
    ctrl.set_voice_style("")
    window.refresh()
    assert window.voice_combo.currentIndex() == 0 and window.voice_combo.currentText() == "她自己的声音"