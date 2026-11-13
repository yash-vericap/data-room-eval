"""The model the checks run on: whether one is set up, its name for the screen, and a client for it."""
from __future__ import annotations

from .providers import JudgeQuotaReached, JudgeUnavailable, chain_label, make_client, settings  # noqa: F401


def credentials_present() -> bool:
    return not settings()["problem"]


def judge_label() -> str:
    cfg = settings()
    if cfg["problem"]:
        return cfg["problem"]
    if len(cfg.get("chain") or []) > 1:
        return f"{chain_label(cfg)} ({cfg['provider']}, free tier)" if cfg["free"] else chain_label(cfg)
    return f"{cfg['model']} via {cfg['provider']}" + (" (free tier)" if cfg["free"] else " (local)")


def _client():
    """A client for the configured model, or for the whole chain when EVAL_JUDGE_CHAIN names several."""
    return make_client()


def excerpt(text: str, quote: str, radius: int) -> str:
    """The part of a page around the quoted words."""
    words = [w for w in quote.split() if len(w) > 3][:4]
    low = text.lower()
    at = next((low.find(w.lower()) for w in words if w.lower() in low), 0)
    start, end = max(0, at - radius), min(len(text), at + radius)
    return ("... " if start else "") + text[start:end] + (" ..." if end < len(text) else "")
