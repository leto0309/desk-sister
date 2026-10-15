"""User settings, stored as JSON under %APPDATA%/ClaudePet."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

INTERVAL_CHOICES = (30, 60, 90, 120, 300, 600)
MODEL_CHOICES = ("haiku", "sonnet")
BACKENDS = ("subscription", "api")  # the user's Claude Code login, or their own Anthropic API key
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
    x: int | None = None
    y: int | None = None

    def normalized(self) -> "Config":
        """Clamp out-of-range values instead of rejecting the whole file."""
        self.interval_sec = min(max(int(self.interval_sec), 15), 3600)
        if self.model not in MODEL_CHOICES:
            self.model = MODEL_CHOICES[0]
        if self.backend not in BACKENDS:
            self.backend = BACKENDS[0]
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
