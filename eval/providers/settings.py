"""The model settings in force: one provider and model, or a chain of them, read from .env."""
from __future__ import annotations

import os

from .policy import PRESETS, _key, _policy_problem, allowed_hosts, data_policy


def _build(name: str, model: str | None = None) -> dict:
    """The settings for one provider and model."""
    if name not in PRESETS:
        return {"provider": name, "model": model or os.environ.get("EVAL_JUDGE_MODEL", ""), "key": "", "base_url": "", "rpm": 0,
                "max_input_chars": 60000, "workers": 1, "passes": 2, "free": False, "policy": data_policy(),
                "allowed_hosts": [],
                "problem": (f"Unknown provider {name!r}. Use one of: {', '.join(PRESETS)}." if name else
                            "No judge model is set up. Put GEMINI_API_KEY in .env, or set EVAL_JUDGE_PROVIDER=local "
                            "for a model on this machine.")}
    cfg = PRESETS[name]
    own = name == ((os.environ.get("EVAL_JUDGE_PROVIDER") or "").strip().lower() or name)
    base_url = ((os.environ.get("EVAL_JUDGE_BASE_URL") if own else "") or cfg["base_url"]).rstrip("/")
    out = {
        "provider": name,
        "model": model or (os.environ.get("EVAL_JUDGE_MODEL") if own else "") or cfg["model"],
        "key": ((os.environ.get("EVAL_JUDGE_API_KEY") if own else "") or _key(cfg["keys"])),
        "base_url": base_url,
        "rpm": float(os.environ.get("EVAL_JUDGE_RPM") or cfg["rpm"]),
        "max_input_chars": int(os.environ.get("EVAL_JUDGE_MAX_INPUT_CHARS") or cfg["max_input_chars"]),
        "workers": cfg["workers"], "passes": max(1, int(os.environ.get("EVAL_JUDGE_PASSES") or 2)),
        "free": cfg["free_tier"] or name == "custom", "policy": data_policy(), "allowed_hosts": allowed_hosts(base_url),
        "problem": None,
    }
    if not out["key"] and name != "local":
        out["problem"] = f"No key for {name}. Set {' or '.join(cfg['keys']) or 'EVAL_JUDGE_API_KEY'} in .env."
    elif not out["base_url"]:
        out["problem"] = "EVAL_JUDGE_BASE_URL is missing."
    elif not out["model"]:
        out["problem"] = "EVAL_JUDGE_MODEL is missing." + (" Name the model your local server runs." if name == "local" else "")
    else:
        out["problem"] = _policy_problem(name, base_url)
    return out


def _default_provider() -> str:
    name = (os.environ.get("EVAL_JUDGE_PROVIDER") or "").strip().lower()
    if not name:
        name = next((p for p, cfg in PRESETS.items() if _key(cfg["keys"])), "")
        if not name and os.environ.get("EVAL_JUDGE_API_KEY") and os.environ.get("EVAL_JUDGE_BASE_URL"):
            name = "custom"
    return name


def chain_entries() -> list[tuple[str, str | None]]:
    """[(provider, model)] from EVAL_JUDGE_CHAIN, or the one configured model when it is not set."""
    default = _default_provider()
    raw = [x.strip() for x in (os.environ.get("EVAL_JUDGE_CHAIN") or "").split(",") if x.strip()]
    if not raw:
        return [(default, None)]
    out = []
    for item in raw:
        name, sep, model = item.partition(":")
        out.append((name.strip().lower(), model.strip() or None) if sep and name.strip().lower() in PRESETS
                   else (default, item))
    return list(dict.fromkeys(out))


def settings() -> dict:
    """The model settings in force: the first usable model, plus "chain" (every usable model, in order) and
    "skipped" (models of the chain that cannot be used, with the reason)."""
    built = [_build(name, model) for name, model in chain_entries()]
    usable = [c for c in built if not c["problem"]]
    skipped = [f"{c['provider']}:{c['model']}: {c['problem']}" for c in built if c["problem"]]
    first = dict(usable[0] if usable else built[0])
    first["chain"] = usable
    first["skipped"] = skipped
    if usable:          # a message must fit every model of the chain
        first["max_input_chars"] = min(c["max_input_chars"] for c in usable)
    return first


def chain_label(cfg: dict | None = None) -> str:
    cfg = cfg or settings()
    if cfg["problem"]:
        return cfg["problem"]
    names = [c["model"] for c in cfg["chain"]]
    return names[0] + (f", then {', '.join(names[1:])} when it is busy or used up" if len(names) > 1 else "")


def validate(v, schema: dict) -> str | None:
    """Checks an answer against the verdict schema. Free models do not all enforce it themselves."""
    if not isinstance(v, dict):
        return "the answer is not a JSON object"
    for name, spec in schema["properties"].items():
        if name not in v:
            return f"field {name!r} is missing"
        if spec["type"] == "array":
            if not isinstance(v[name], list) or not all(isinstance(x, str) for x in v[name]):
                return f"field {name!r} must be a list of case IDs"
        elif not isinstance(v[name], str):
            return f"field {name!r} must be text"
        elif "enum" in spec and v[name] not in spec["enum"]:
            return f"field {name!r} has the value {v[name]!r}, which is not allowed"
    return None
