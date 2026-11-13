"""The providers, the errors, and the data policy: which hosts and providers a request may go to, and the
check every request body passes just before it leaves the machine."""
from __future__ import annotations

import ipaddress
import os
import urllib.parse


# rpm and max_input_chars are cautious starting values; the provider's own limits page is the reference.
PRESETS = {
    "gemini": {"base_url": "https://generativelanguage.googleapis.com/v1beta/openai", "model": "gemini-flash-latest",
               "keys": ["GEMINI_API_KEY", "GOOGLE_API_KEY"], "rpm": 8, "max_input_chars": 60000, "workers": 1, "free_tier": True},
    "github": {"base_url": "https://models.github.ai/inference", "model": "openai/gpt-4.1-mini",
               "keys": ["GITHUB_MODELS_TOKEN"], "rpm": 10, "max_input_chars": 24000, "workers": 1, "free_tier": True},
    "local": {"base_url": "http://localhost:11434/v1", "model": "", "keys": [], "rpm": 0, "max_input_chars": 24000,
              "workers": 1, "free_tier": False},
    "custom": {"base_url": "", "model": "", "keys": [], "rpm": 30, "max_input_chars": 60000, "workers": 1,
               "free_tier": False},
}
FORBIDDEN_KEYS = {"tools", "tool_choice", "functions", "function_call", "mcp_servers", "web_search", "web_search_options",
                  "plugins", "files", "file_ids", "attachments", "urls", "url_context", "tool_resources"}


class JudgeUnavailable(RuntimeError):
    """The judge cannot run at all: no key, wrong key, unknown model."""


class ModelBusy(RuntimeError):
    """One model of a chain cannot answer for a while (overloaded, rate-limited or slow). The chain moves on."""

    def __init__(self, message: str, seconds: float = 60.0):
        super().__init__(message)
        self.seconds = seconds


class JudgeQuotaReached(RuntimeError):
    """The provider's free allowance is used up for now. Verdicts so far are kept; run again later."""


def _key(names: list[str]) -> str:
    return next((os.environ[n] for n in names if os.environ.get(n)), "")


def _host(url: str) -> str:
    return (urllib.parse.urlsplit(url).hostname or "").lower()


def is_local_host(host: str) -> bool:
    """True for this machine and for private-network addresses."""
    host = (host or "").lower().strip("[]")
    if host in ("localhost", "host.docker.internal") or host.endswith((".local", ".internal", ".lan")):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_loopback or ip.is_private


def data_policy() -> str:
    return "open" if (os.environ.get("EVAL_DATA_POLICY") or "strict").strip().lower() == "open" else "strict"


def _names(var: str) -> list[str]:
    return [x.strip().lower() for x in (os.environ.get(var) or "").split(",") if x.strip()]


def allowed_hosts(base_url: str) -> list[str]:
    return _names("EVAL_ALLOWED_HOSTS") or [h for h in [_host(base_url)] if h]


def check_request(url: str, body: dict, allowed: list[str]) -> None:
    """The last check before anything leaves the machine. Raises JudgeUnavailable when the body carries
    tools of any kind or the host is not an allowed one."""
    bad = sorted(FORBIDDEN_KEYS & set(body))
    if bad:
        raise JudgeUnavailable(f"Refused to send: the request carries {', '.join(bad)}. The model is never given tools.")
    host = _host(url)
    if not host or host not in allowed:
        raise JudgeUnavailable(f"Refused to send: {host or url!r} is not an allowed host. "
                               f"Allowed: {', '.join(allowed) or 'none'} (EVAL_ALLOWED_HOSTS).")


def _policy_problem(name: str, base_url: str) -> str | None:
    if data_policy() == "open" or name in _names("EVAL_TRUSTED_PROVIDERS"):
        return None
    if name == "local" or (name == "custom" and is_local_host(_host(base_url))):
        return None if is_local_host(_host(base_url)) else (
            f"The local provider points at {_host(base_url)!r}, which is not this machine or a private network.")
    if PRESETS[name]["free_tier"]:
        return (f"The data policy is strict, so the free tier {name!r} is refused: its terms may keep or train on what "
                f"is sent, and the judge sends document pages and answer-key cases. Use a local model "
                f"(EVAL_JUDGE_PROVIDER=local), or allow it on purpose with EVAL_TRUSTED_PROVIDERS={name} "
                f"or EVAL_DATA_POLICY=open.")
    return (f"The data policy is strict, so the endpoint {_host(base_url) or name!r} is refused. Name the provider in "
            f"EVAL_TRUSTED_PROVIDERS, use a local model, or set EVAL_DATA_POLICY=open.")
