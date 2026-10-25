"""User settings, stored as JSON under %APPDATA%/ClaudePet."""
from __future__ import annotations

import json
import math
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from .bedtime import MODES as BEDTIME_MODES
from .bedtime import NIGHT_STARTS
from .days import clean_birthday
from .i18n import CHOICES as LANGUAGES
from .persona import SUMMARY_HOURS
from .timers import BREAK_RANGE, FOCUS_RANGE
from .voice import STYLES as VOICE_STYLES
from .updates import parse_version
from .providers import BACKENDS, clean_custom_models  # every way she can think

BLINK_CHOICES = ("off", "few", "normal", "often")
INTERVAL_CHOICES = (30, 60, 90, 120, 300, 600)
MODEL_CHOICES = ("haiku", "sonnet")  # tiers: fast and cheap / smarter (each provider maps them to its models)
WATCH_MODES = ("blocklist", "allowlist")

# Matched case-insensitively against the foreground window title and process name.
# A hit means no screenshot is taken or sent.
DEFAULT_BLOCKLIST = [
    "password", "密码", "1password", "bitwarden", "keepass", "lastpass", "credential",
    "bank", "银行", "支付", "alipay", "paypal", "wallet", "钱包",
    "wechat", "weixin", "微信", "qq.exe", "telegram", "whatsapp", "line.exe", "signal",
    "inprivate", "incognito", "无痕", "隐身",
    "验证码", "2fa", "authenticator",
]


def app_data_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home() / ".config")
    return Path(base) / "ClaudePet"


def config_path() -> Path:
    return app_data_dir() / "config.json"


@dataclass
class Config:
    interval_sec: int = 90
    model: str = "haiku"
    backend: str = "subscription"
    custom_models: dict[str, str] = field(default_factory=dict)  # provider -> model ID overriding the tier
    paused: bool = False
    claude_path: str = ""
    blocklist: list[str] = field(default_factory=lambda: list(DEFAULT_BLOCKLIST))
    # "blocklist": look at everything except blocked windows; "allowlist": only allowlisted programs
    # (the blocklist still applies on top).
    watch_mode: str = "blocklist"
    allowlist: list[str] = field(default_factory=list)
    sleep_after_sec: int = 600
    dwell_sec: int = 20
    failure_limit: int = 3
    failure_pause_min: int = 30
    quiet_fullscreen: bool = True
    self_talk: bool = True
    companion_memory: bool = True
    claude_link: bool = False
    self_talk_min_sec: int = 180
    self_talk_max_sec: int = 600
    timeout_sec: int = 120
    sprite_height: int = 220
    walking: bool = True  # strolls along the bottom of the screen now and then
    blink: str = "normal"  # off | few | normal | often
    talk_mouth: bool = True  # her mouth moves while her words appear
    voice: bool = False  # Animalese babble as she talks (off unless chosen)
    voice_style: str = "squeaky"
    voice_volume: int = 60  # 0-100
    focus_min: int = 25  # the focus timer: minutes of focus, then of a break
    break_min: int = 5
    body_motion: bool = True  # a swing when carried, a landing squash, a little mood reaction (can be switched off)
    head_motion: bool = False  # off unless chosen: a nod as she starts to talk, a tilt now and then, a duck when patted
    birthday: str = ""  # "MM-DD" for a birthday wish, "" for none
    check_updates: bool = True  # look for a newer release on GitHub, at most once a day
    update_checked_at: float = 0.0  # wall-clock time of the last successful check
    update_seen: str = ""  # the newest version she already told 主人 about
    update_latest: str = ""  # the latest release the last successful check found
    daily_summary_hour: int = 21  # from this hour she sums up the day once; 0 = never
    summary_on: str = ""  # the day (YYYY-MM-DD) of the last summary
    language: str = ""  # "" follows the Windows display language; "zh" or "en"
    greeted_on: str = ""  # the day (YYYY-MM-DD) she last said her first hello, so a restart does not repeat it
    bedtime_reminder: str = "nightly"  # off | nightly | every_2h (see bedtime.py)
    night_start_hour: int = 23
    bedtime_reminded_at: float = 0.0  # wall-clock time of the last reminder, shared by comments and self-talk
    x: int | None = None
    y: int | None = None

    def normalized(self) -> "Config":
        """Clamp out-of-range values instead of rejecting the whole file."""
        self.interval_sec = min(max(int(self.interval_sec), 15), 3600)
        if self.model not in MODEL_CHOICES:
            self.model = MODEL_CHOICES[0]
        if self.backend not in BACKENDS:
            self.backend = BACKENDS[0]
        self.custom_models = clean_custom_models(self.custom_models)
        self.paused = bool(self.paused)
        self.claude_path = str(self.claude_path or "")
        # A wrong type must never silently become an empty blocklist: fall back to the defaults instead.
        if isinstance(self.blocklist, list) and all(isinstance(item, str) for item in self.blocklist):
            self.blocklist = [item.strip() for item in self.blocklist if item.strip()]
        else:
            self.blocklist = list(DEFAULT_BLOCKLIST)
        if self.watch_mode not in WATCH_MODES:
            self.watch_mode = WATCH_MODES[0]
        if isinstance(self.allowlist, list) and all(isinstance(item, str) for item in self.allowlist):
            self.allowlist = [item.strip() for item in self.allowlist if item.strip()]
        else:
            self.allowlist = []  # a broken allowlist allows nothing rather than everything
        self.sleep_after_sec = min(max(int(self.sleep_after_sec), 60), 86400)
        self.dwell_sec = min(max(int(self.dwell_sec), 0), 600)
        self.failure_limit = min(max(int(self.failure_limit), 1), 20)
        self.failure_pause_min = min(max(int(self.failure_pause_min), 1), 1440)
        self.quiet_fullscreen = bool(self.quiet_fullscreen)
        self.self_talk = bool(self.self_talk)
        self.companion_memory = bool(self.companion_memory)
        self.claude_link = bool(self.claude_link)
        self.self_talk_min_sec = min(max(int(self.self_talk_min_sec), 30), 3600)
        self.self_talk_max_sec = min(max(int(self.self_talk_max_sec), self.self_talk_min_sec), 7200)
        self.timeout_sec = min(max(int(self.timeout_sec), 20), 600)
        self.sprite_height = min(max(int(self.sprite_height), 100), 600)
        self.walking = bool(self.walking)
        if self.blink not in BLINK_CHOICES:
            self.blink = "normal"
        self.birthday = clean_birthday(self.birthday)
        if not isinstance(self.greeted_on, str) or len(self.greeted_on) != 10:
            self.greeted_on = ""
        if not isinstance(self.head_motion, bool):
            self.head_motion = False
        if not isinstance(self.body_motion, bool):
            self.body_motion = True
        for name, default, (low, high) in (("focus_min", 25, FOCUS_RANGE), ("break_min", 5, BREAK_RANGE)):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                value = default
            setattr(self, name, min(max(value, low), high))
        if not isinstance(self.voice, bool):
            self.voice = False
        if not isinstance(self.voice_style, str) or self.voice_style not in VOICE_STYLES:
            self.voice_style = "squeaky"
        if isinstance(self.voice_volume, bool) or not isinstance(self.voice_volume, int):
            self.voice_volume = 60
        self.voice_volume = min(max(self.voice_volume, 0), 100)
        if not isinstance(self.talk_mouth, bool):  # null, 0, ""... are not a choice: back to the default
            self.talk_mouth = True
        if self.bedtime_reminder not in BEDTIME_MODES:
            self.bedtime_reminder = "nightly"
        if self.night_start_hour not in NIGHT_STARTS:
            self.night_start_hour = 23
        try:
            reminded = float(self.bedtime_reminded_at)
        except (TypeError, ValueError, OverflowError):  # a broken value (say 10**400) only forgets the last reminder
            reminded = 0.0
        # A real reminder time lies between 2001 and 2286; anything else (1, true, 1e12) means none.
        self.bedtime_reminded_at = reminded if math.isfinite(reminded) and 1e9 <= reminded <= 1e10 else 0.0
        if self.daily_summary_hour not in SUMMARY_HOURS or isinstance(self.daily_summary_hour, bool):
            self.daily_summary_hour = 21
        if not isinstance(self.summary_on, str) or len(self.summary_on) != 10:
            self.summary_on = ""
        if self.language not in LANGUAGES:
            self.language = ""
        if not isinstance(self.check_updates, bool):
            self.check_updates = True
        try:
            checked = float(self.update_checked_at)
        except (TypeError, ValueError, OverflowError):
            checked = 0.0
        self.update_checked_at = checked if math.isfinite(checked) and 1e9 <= checked <= 1e10 else 0.0
        if parse_version(self.update_seen) is None:
            self.update_seen = ""
        if parse_version(self.update_latest) is None:
            self.update_latest = ""
        for name in ("x", "y"):
            value = getattr(self, name)
            setattr(self, name, None if value is None else int(value))
        return self


def load_config(path: Path | None = None) -> Config:
    path = path or config_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Config()
    if not isinstance(raw, dict):
        return Config()
    known = {f.name for f in fields(Config)}
    try:
        return Config(**{k: v for k, v in raw.items() if k in known}).normalized()
    except (TypeError, ValueError, OverflowError):  # e.g. 1e309 parses as inf
        return Config()


def save_config(config: Config, path: Path | None = None) -> None:
    path = path or config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(asdict(config), ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)
