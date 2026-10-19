"""Every way she can think: a local CLI on the user's subscription, or the user's own API key.

The config keeps the tier as "haiku" (fast and cheap) or "sonnet" (smarter); each provider maps those two
tiers to its own model IDs. A custom model ID per provider overrides the tier, so a renamed or retired
model never needs an update of this program.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

CLAUDE_CLI, ANTHROPIC, OPENAI_COMPATIBLE, CODEX_CLI = "claude-cli", "anthropic", "openai-compatible", "codex-cli"
TIERS = ("haiku", "sonnet")
TIER_NAMES = {"haiku": "快速省钱", "sonnet": "更聪明"}
MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@-]{0,99}$")  # what a custom model ID may look like


@dataclass(frozen=True)
class Provider:
    id: str
    label: str  # menu and settings
    kind: str
    presets: dict[str, str] = field(default_factory=dict)  # tier -> model ID ("" = the CLI's own default)
    base_url: str = ""  # OpenAI-compatible endpoints only
    vault_entry: str = ""  # Windows Credential Manager entry for the key; "" = no key (a CLI login)
    key_page: str = ""  # where a user gets a key
    company: str = ""
    paid: bool = False  # billed per use on the user's own key
    tier_notes: dict[str, str] = field(default_factory=dict)  # shown when a tier has no model ID of its own

    @property
    def needs_key(self) -> bool:
        return bool(self.vault_entry)


PROVIDERS: dict[str, Provider] = {
    p.id: p for p in (
        Provider("subscription", "Claude Code 订阅（默认）", CLAUDE_CLI, {"haiku": "haiku", "sonnet": "sonnet"},
                 company="Anthropic"),
        Provider("codex", "Codex（ChatGPT 订阅）", CODEX_CLI, {"haiku": "", "sonnet": ""}, company="OpenAI",
                 tier_notes={"haiku": "账号默认模型，低推理强度", "sonnet": "账号默认模型，中等推理强度"}),
        Provider("api", "Anthropic API Key", ANTHROPIC, {"haiku": "claude-haiku-5-5", "sonnet": "claude-sonnet-5-5"},
                 vault_entry="Desk Sister: Anthropic", key_page="https://platform.claude.com/settings/keys",
                 company="Anthropic", paid=True),
        Provider("openai", "OpenAI API Key", OPENAI_COMPATIBLE, {"haiku": "gpt-6-luna", "sonnet": "gpt-6.1-sol"},
                 base_url="https://api.openai.com/v1", vault_entry="Desk Sister: OpenAI",
                 key_page="https://platform.openai.com/api-keys", company="OpenAI", paid=True),
        Provider("deepseek", "DeepSeek API Key", OPENAI_COMPATIBLE, {"haiku": "deepseek-flash", "sonnet": "deepseek-v4-pro"},
                 base_url="https://api.deepseek.com", vault_entry="Desk Sister: DeepSeek",
                 key_page="https://platform.deepseek.com/api_keys", company="DeepSeek", paid=True),
        Provider("gemini", "Gemini API Key", OPENAI_COMPATIBLE, {"haiku": "gemini-3.5-flash", "sonnet": "gemini-3.8-flash"},
                 base_url="https://generativelanguage.googleapis.com/v1beta/openai/", vault_entry="Desk Sister: Gemini",
                 key_page="https://aistudio.google.com/apikey", company="Google", paid=True),
    )
}
BACKENDS = tuple(PROVIDERS)


def model_for(provider: Provider, tier: str, custom: str = "") -> str:
    """The model to ask: the custom ID when one is set, else the tier's preset ("" = the CLI's default)."""
    return custom or provider.presets.get(tier, provider.presets.get("haiku", ""))


def model_label(provider: Provider, tier: str) -> str:
    preset = provider.presets.get(tier, "") or provider.tier_notes.get(tier, "账号默认模型")
    return f"{TIER_NAMES[tier]}（{preset}）"


def clean_custom_models(raw: object) -> dict[str, str]:
    """Only known providers and plausible model IDs survive a hand-edited config."""
    if not isinstance(raw, dict):
        return {}
    return {k: v.strip() for k, v in raw.items()
            if k in PROVIDERS and isinstance(v, str) and MODEL_ID.match(v.strip())}
