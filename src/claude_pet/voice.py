"""Her voice: Animalese-style babble, one short synthesised vowel per character as her words appear.

Nothing recorded: every blip is additive synthesis of a few harmonics shaped by vowel formants, made here with the
standard library only. The same character always gets the same vowel and pitch step, so a line sounds the same each
time; her mood moves the pitch and the spread.
"""
from __future__ import annotations

import array
import io
import logging
import math
import random
import sys
import threading
import time
import wave
from functools import lru_cache
from pathlib import Path

from .i18n import N_

log = logging.getLogger(__name__)

RATE = 22050
VOWELS = {  # formants (Hz), raised a little for a small voice
    "a": (920, 1380, 2880), "i": (345, 2650, 3450), "u": (400, 920, 2650), "e": (575, 2180, 3000), "o": (575, 1035, 2760),
}
VOWEL_ORDER = "aiueo"
STYLES = {  # base pitch (Hz), brightness (how far the harmonics reach); the first is the default
    "squeaky": (560, 1.1),
    "bright": (440, 1.0),
    "soft": (360, 0.75),
    "low": (280, 0.85),
}
STYLE_NAMES = {"squeaky": N_("尖细可爱"), "bright": N_("清亮"), "soft": N_("柔和"), "low": N_("低沉")}  # shown through tr()
MOODS = {  # pitch factor, spread of the pitch steps
    "idle": (1.0, 1.0), "talk": (1.0, 1.0), "happy": (1.12, 1.2), "think": (0.95, 0.7), "panic": (1.2, 1.8),
    "angry": (0.88, 1.3), "sad": (0.82, 0.6),
}
STEPS = 9  # pitch steps per voice, cached
SILENT = set("，。！？、…～,.!?;；：:（）()「」『』—\n \t\"'“”")


def _vowel(ch: str) -> str:
    lower = ch.lower()
    if lower in VOWEL_ORDER:
        return lower
    return VOWEL_ORDER[ord(ch) * 7 % len(VOWEL_ORDER)]


def _step(ch: str) -> int:
    return ord(ch) * 7919 % STEPS


@lru_cache(maxsize=512)
def _blip(vowel: str, f0: float, brightness: float, samples: int) -> tuple[float, ...]:
    """One syllable: harmonics of f0 weighted by the vowel's formants, a quick attack, a falling pitch, a soft end."""
    formants = VOWELS[vowel]
    harmonics = []
    h = 1
    while h * f0 < 5000 * brightness and h <= 24:
        freq = h * f0
        gain = sum(math.exp(-((freq - f) / (90 + f * 0.08)) ** 2) * (1.0 / (1 + i)) for i, f in enumerate(formants))
        gain += 0.15 / h  # some body below the formants
        harmonics.append((h, gain))
        h += 1
    total = sum(g for _, g in harmonics) or 1.0
    attack = max(1, int(RATE * 0.004))
    out = []
    phase = 0.0
    for n in range(samples):
        t = n / samples
        pitch = f0 * (1.0 + 0.10 * (1.0 - t))  # a little fall: cute, not robotic
        phase += 2 * math.pi * pitch / RATE
        value = sum(g * math.sin(k * phase) for k, g in harmonics) / total
        envelope = min(1.0, n / attack) * (1.0 - t) ** 1.6
        out.append(value * envelope)
    return tuple(out)


def render(text: str, mood: str = "talk", style: str = "squeaky", volume: int = 60, char_ms: int = 35,
           skip_ms: float = 0) -> bytes:
    """The babble for `text`, one blip per character every `char_ms`, as a 16-bit mono WAV. Empty for silence.

    `skip_ms` drops that much from the start, so a line that took a while to make still lines up with the typing."""
    return _wav(_pcm(text, mood, style, volume, char_ms), skip_ms)


def _pcm(text: str, mood: str, style: str, volume: int, char_ms: int) -> bytes:
    """The whole line as 16-bit samples; empty when nothing in it is voiced."""
    if mood not in MOODS or not text.strip():
        return b""
    base, brightness = STYLES.get(style, STYLES["bright"])
    factor, spread = MOODS[mood]
    slot = max(1, int(RATE * char_ms / 1000))
    blip_len = max(int(RATE * 0.03), min(int(RATE * 0.09), int(slot * 0.9)))
    pcm = [0.0] * (slot * len(text) + blip_len)
    voiced = False
    for i, ch in enumerate(text):
        if ch in SILENT or ch.isspace():
            continue
        offset = (_step(ch) - (STEPS - 1) / 2) / ((STEPS - 1) / 2)  # -1 .. 1
        f0 = round(base * factor * (1 + 0.14 * spread * offset), 1)
        blip = _blip(_vowel(ch), f0, brightness, blip_len)
        start = i * slot
        for j, v in enumerate(blip):
            pcm[start + j] += v
        voiced = True
    if not voiced:
        return b""
    gain = 0.6 * max(0, min(volume, 100)) / 100
    frames = bytearray()
    for v in pcm:
        sample = int(max(-1.0, min(1.0, v * gain)) * 32767)
        frames += sample.to_bytes(2, "little", signed=True)
    return bytes(frames)


def _wav(pcm: bytes, skip_ms: float = 0) -> bytes:
    """`pcm` from `skip_ms` on, as a WAV; empty when nothing audible is left."""
    pcm = pcm[max(0, int(RATE * skip_ms / 1000)) * 2:]
    if not pcm.strip(b"\x00"):
        return b""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(RATE)
        out.writeframes(pcm)
    return buffer.getvalue()


# ---- little sounds for what happens to her (same switch, style and volume as her voice) ----------------------
EFFECTS = ("pat", "lift", "land", "snore")
EFFECT_SLACK_MS = 40  # an effect made later than this starts part way in, like a line
EFFECT_GAIN = 0.45
EFFECT_LEVEL = {"pat": 0.85, "lift": 0.8, "land": 0.6, "snore": 1.0}  # each just under her voice at the same volume


def _glide(f_start: float, f_end: float, seconds: float, harmonics=((1, 1.0), (2, 0.3), (3, 0.1)),
           attack: float = 0.006, fall: float = 1.5) -> list[float]:
    """A tone sliding from one pitch to another: a quick start, a soft end."""
    count = max(1, int(RATE * seconds))
    attack_n = max(1, int(RATE * attack))
    total = sum(g for _, g in harmonics)
    out, phase = [], 0.0
    for n in range(count):
        t = n / count
        phase += 2 * math.pi * (f_start + (f_end - f_start) * t) / RATE
        value = sum(g * math.sin(k * phase) for k, g in harmonics) / total
        out.append(value * min(1.0, n / attack_n) * (1.0 - t) ** fall)
    return out


def _silence(seconds: float) -> list[float]:
    return [0.0] * int(RATE * seconds)


def _overlay(base: list[float], extra: list[float], at: int = 0) -> list[float]:
    out = base + [0.0] * max(0, at + len(extra) - len(base))
    for i, v in enumerate(extra):
        out[at + i] += v
    return out


def _effect_shape(name: str, base: float) -> list[float]:
    if name == "pat":  # two happy little chirps
        return _glide(base * 1.3, base * 1.6, 0.09) + _silence(0.04) + _glide(base * 1.4, base * 1.9, 0.12)
    if name == "lift":  # whoop! up she goes
        return _glide(base * 1.0, base * 2.2, 0.17, attack=0.004, fall=0.8)
    if name == "land":  # a soft bump and a tiny tick
        bump = _glide(150, 70, 0.14, harmonics=((1, 1.0), (2, 0.15)), attack=0.002, fall=2.0)
        return _overlay(bump, [0.35 * v for v in _glide(base * 2, base * 2, 0.025, attack=0.001)])
    # snore: a slow low breath in, and a little whistle out (zzz~pyu)
    rng = random.Random(7)
    count = int(RATE * 0.9)
    breath, smooth = [], 0.0
    for n in range(count):
        smooth += 0.08 * (rng.uniform(-1, 1) - smooth)  # soft, low noise
        swell = math.sin(math.pi * n / count)
        breath.append(swell * (0.6 * smooth + 0.4 * math.sin(2 * math.pi * 90 * n / RATE)))
    return breath + _silence(0.08) + [0.6 * v for v in _glide(base * 1.8, base * 1.2, 0.28, fall=1.2)]


@lru_cache(maxsize=64)
def effect_pcm(name: str, style: str = "squeaky", volume: int = 60) -> bytes:
    """One of EFFECTS as 16-bit samples, pitched by her voice style; empty when unknown or silent."""
    if name not in EFFECTS:
        return b""
    base, _brightness = STYLES.get(style, STYLES["squeaky"])
    gain = EFFECT_GAIN * EFFECT_LEVEL[name] * max(0, min(volume, 100)) / 100
    frames = bytearray()
    for v in _effect_shape(name, base):
        frames += int(max(-1.0, min(1.0, v * gain)) * 32767).to_bytes(2, "little", signed=True)
    return bytes(frames) if frames.strip(b"\x00") else b""


def _mix(first: bytes, second: bytes) -> bytes:
    """Two 16-bit sample runs played together (the longer one sets the length)."""
    a = array.array("h", first)
    b = array.array("h", second)
    if len(a) < len(b):
        a, b = b, a
    for i, v in enumerate(b):
        a[i] = max(-32768, min(32767, a[i] + v))
    return a.tobytes()


class Player:
    """Plays one line at a time, made on a worker thread; a newer line or stop() cuts the current one at once.

    winsound plays files asynchronously (not memory), so each line goes to its own small WAV in `folder` and the
    previous one is removed once the new one plays. The lock only guards the serial and the play/stop calls, never
    the file writing, so the GUI thread never waits on a slow disk."""

    def __init__(self, folder: Path, play=None, clock=time.monotonic, spawn=None) -> None:
        self.folder = folder
        self._play = play or _winsound_play
        self._spawn = spawn or _spawn
        self._clock = clock
        self._lock = threading.Lock()
        self._serial = 0
        self._current: Path | None = None
        self._effect: tuple[bytes, float] | None = None  # the last little sound and when it began
        self._line: tuple[tuple, float] | None = None  # the last line (what to render it from) and when it began
        for old in folder.glob("voice-*.wav"):  # left from last time
            _remove(old)

    def say(self, text: str, mood: str, style: str, volume: int, char_ms: int, spawn=None) -> None:
        with self._lock:
            self._serial += 1
            serial = self._serial
            self._quiet()  # the last line stops now, not when this one is ready
            effect = self._effect
            begun = self._clock()  # the typing starts now; the sound catches up to it
            self._line = ((text, mood, style, volume, char_ms), begun)

        def make() -> bytes:
            pcm = _pcm(text, mood, style, volume, char_ms)
            if pcm and effect is not None:  # a little sound still ringing goes on under her words
                sound, started = effect
                rest = sound[int((begun - started) * RATE) * 2:] if begun >= started else b""
                pcm = _mix(pcm, rest) if rest else pcm
            return pcm

        (spawn or self._spawn)(lambda: self._make_and_play(serial, begun, make, char_ms))

    def effect(self, name: str, style: str, volume: int, spawn=None) -> None:
        """A little sound for what just happened to her. One sound plays at a time, so they share: a line she
        starts meanwhile carries the rest of it on, and the rest of a line she is saying goes on under it."""
        sound = effect_pcm(name, style, volume)
        if not sound:
            return
        with self._lock:
            self._serial += 1
            serial = self._serial
            begun = self._clock()
            self._effect = (sound, begun)
            line = self._line

        def make() -> bytes:
            if line is None:
                return sound
            args, started = line
            rest = _pcm(*args)[max(0, int((begun - started) * RATE)) * 2:]
            return _mix(sound, rest) if rest else sound

        (spawn or self._spawn)(lambda: self._make_and_play(serial, begun, make, EFFECT_SLACK_MS))

    def _make_and_play(self, serial, begun, make, char_ms) -> None:
        if serial != self._serial:
            return
        path = self.folder / f"voice-{serial}.wav"
        pcm = make()
        written = False
        data = b""
        for _attempt in range(2):  # once more if the write itself put her a character or more behind
            late_ms = self._late_ms(begun)
            data = _wav(pcm, late_ms)
            if not data:  # nothing to say, or the typing is already past it all
                break
            try:
                self.folder.mkdir(parents=True, exist_ok=True)
                written = True
                _write(path, data)
            except OSError as exc:
                log.warning("could not make her voice: %s", exc)
                data = b""
                break
            now_ms = self._late_ms(begun)
            if not _wav(pcm, now_ms):  # the line ended while it was being written
                data = b""
                break
            if now_ms - late_ms < char_ms:
                break
        else:  # every write left her a character or more behind: better silent than out of step
            data = b""
        played = None
        with self._lock:
            if serial == self._serial and data:
                try:
                    self._play(path)
                    played, self._current = self._current, path
                except (OSError, RuntimeError) as exc:
                    log.warning("could not play her voice: %s", exc)
        if played is not None:
            _remove(played)  # the line before this one
        if written and self._current != path:
            _remove(path)  # superseded, failed or too late: never played

    def _late_ms(self, begun: float) -> float:
        return (self._clock() - begun) * 1000

    def stop(self) -> None:
        with self._lock:
            self._serial += 1
            self._effect = self._line = None  # stopped means stopped: nothing comes back with the next sound
            self._quiet()
            done, self._current = self._current, None
        if done is not None:
            self._spawn(lambda: _remove(done))  # off the GUI thread: the disk may be slow

    def _quiet(self) -> None:
        try:
            self._play(None)
        except (OSError, RuntimeError) as exc:
            log.warning("could not stop her voice: %s", exc)


def _write(path: Path, data: bytes) -> None:
    path.write_bytes(data)


def _remove(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:  # still held by the sound system; cleared next start
        log.debug("could not remove %s: %s", path.name, exc)


def _spawn(fn) -> None:
    threading.Thread(target=fn, daemon=True, name="voice").start()


def _winsound_play(path: Path | None) -> None:
    if sys.platform != "win32":
        return
    import winsound

    if path is None:
        winsound.PlaySound(None, 0)  # stops what is playing
    else:
        winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
