"""Which model the judge runs on, and the rules on what may be sent to it.

The judge talks to one OpenAI-style chat endpoint. Three presets exist:
  github   GitHub Models (free GPT models with a GitHub account). A free tier: its terms may keep inputs.
  local    a model on this machine or a private network (for example Ollama at http://localhost:11434/v1).
  custom   another OpenAI-style endpoint, with EVAL_JUDGE_BASE_URL, EVAL_JUDGE_API_KEY and EVAL_JUDGE_MODEL.

Settings, read from the environment or the .env file:
  GITHUB_MODELS_TOKEN   the GitHub token (account permission "Models: Read-only")
  EVAL_JUDGE_PROVIDER   github | local | custom (when unset: github if its token is present)
  EVAL_JUDGE_MODEL      model name, when the default is not wanted (required for local and custom)
  EVAL_JUDGE_RPM        most requests per minute to send
  EVAL_JUDGE_PASSES     how many times each finding is judged (default 2)
  EVAL_JUDGE_MAX_INPUT_CHARS   largest message to send; longer ones carry page excerpts instead of full pages

Data security (see the README, "Data security and storage"):
  EVAL_DATA_POLICY        strict (default) | open. Strict allows a local model, and providers named in
                          EVAL_TRUSTED_PROVIDERS. A free tier is refused unless it is allowed on purpose.
  EVAL_TRUSTED_PROVIDERS  comma-separated provider names allowed under the strict policy
  EVAL_ALLOWED_HOSTS      comma-separated hosts a request may go to (default: the configured provider's host)
No request ever carries tools, functions, MCP servers, web search or files; every body is checked before sending.
"""
from __future__ import annotations

import ipaddress
import json
import os
import re
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

# rpm and max_input_chars are cautious starting values; the provider's own limits page is the reference.
PRESETS = {
    "github": {"base_url": "https://models.github.ai/inference", "model": "openai/gpt-4.1-mini",
               "keys": ["GITHUB_MODELS_TOKEN"], "rpm": 10, "max_input_chars": 24000, "workers": 1, "free_tier": True},
    "local": {"base_url": "http://localhost:11434/v1", "model": "", "keys": [], "rpm": 0, "max_input_chars": 24000,
              "workers": 1, "free_tier": False},
    "custom": {"base_url": "", "model": "", "keys": [], "rpm": 30, "max_input_chars": 60000, "workers": 1,
               "free_tier": False},
}
FORBIDDEN_KEYS = {"tools", "tool_choice", "functions", "function_call", "mcp_servers", "web_search", "web_search_options",
                  "plugins", "files", "file_ids", "attachments", "urls", "url_context", "tool_resources"}
FAMILIES = {"gpt": ["gpt", "chatgpt", "openai"], "gemini": ["gemini"], "claude": ["claude"], "grok": ["grok"],
            "deepseek": ["deepseek"], "llama": ["llama"], "mistral": ["mistral"], "qwen": ["qwen"]}


class JudgeUnavailable(RuntimeError):
    """The judge cannot run at all: no key, wrong key, unknown model."""


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


def settings() -> dict:
    name = (os.environ.get("EVAL_JUDGE_PROVIDER") or "").strip().lower()
    if not name:
        name = next((p for p, cfg in PRESETS.items() if _key(cfg["keys"])), "")
        if not name and os.environ.get("EVAL_JUDGE_API_KEY") and os.environ.get("EVAL_JUDGE_BASE_URL"):
            name = "custom"
    if name not in PRESETS:
        return {"provider": name, "model": os.environ.get("EVAL_JUDGE_MODEL", ""), "key": "", "base_url": "", "rpm": 0,
                "max_input_chars": 60000, "workers": 1, "passes": 2, "free": False, "policy": data_policy(),
                "allowed_hosts": [],
                "problem": (f"Unknown EVAL_JUDGE_PROVIDER {name!r}. Use one of: {', '.join(PRESETS)}." if name else
                            "No judge model is set up. Set EVAL_JUDGE_PROVIDER=local for a model on this machine, "
                            "or put GITHUB_MODELS_TOKEN in .env.")}
    cfg = PRESETS[name]
    base_url = (os.environ.get("EVAL_JUDGE_BASE_URL") or cfg["base_url"]).rstrip("/")
    out = {
        "provider": name,
        "model": os.environ.get("EVAL_JUDGE_MODEL") or cfg["model"],
        "key": os.environ.get("EVAL_JUDGE_API_KEY") or _key(cfg["keys"]),
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


def family(text: str) -> str | None:
    text = text.lower()
    return next((fam for fam, words in FAMILIES.items() if any(w in text for w in words)), None)


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


def _ssl_context() -> ssl.SSLContext:
    """Uses the certifi root certificates when they are installed: a python.org Python on macOS has none of its own."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


class ChatClient:
    """One OpenAI-style /chat/completions endpoint, with pacing for rate limits. Every call is stateless:
    a system prompt and one message, no history, no tools."""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.format = "json_schema"       # falls back to json_object, then to plain text, if the provider refuses
        self.send_temperature = True
        self._lock, self._last = threading.Lock(), 0.0

    def _pace(self):
        if self.cfg["rpm"] <= 0:
            return
        with self._lock:
            wait = self._last + 60.0 / self.cfg["rpm"] - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()

    def _post(self, body: dict) -> tuple[int, dict, dict]:
        url = self.cfg["base_url"] + "/chat/completions"
        check_request(url, body, self.cfg.get("allowed_hosts") or allowed_hosts(self.cfg["base_url"]))
        headers = {"Content-Type": "application/json", "User-Agent": "dataroom-eval-judge"}
        if self.cfg.get("key"):
            headers["Authorization"] = f"Bearer {self.cfg['key']}"
        req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=180, context=_ssl_context() if url.startswith("https") else None) as resp:
                raw = resp.read().decode(errors="replace")
                try:
                    data = json.loads(raw or "{}")
                except json.JSONDecodeError as e:   # a 200 that is not JSON: this is not the API answering
                    raise JudgeUnavailable(f"{self.cfg['base_url']} answered with text instead of JSON ({raw.strip()[:80]!r}). "
                                           f"The service is not answering as the API right now; try again later.") from e
                return resp.status, data, dict(resp.headers)
        except urllib.error.HTTPError as e:
            raw = e.read().decode(errors="replace")
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                data = {"error": {"message": raw[:300]}}
            return e.code, data, dict(e.headers or {})

    def complete(self, model: str, system: str, message: str, schema: dict) -> dict:
        """Returns {"verdict", "error", "input_tokens", "output_tokens"}. Raises JudgeUnavailable or JudgeQuotaReached."""
        fields = ", ".join(f'"{k}" ({" | ".join(s["enum"]) if "enum" in s else ("list of IDs" if s["type"] == "array" else "text")})'
                           for k, s in schema["properties"].items())
        system = system + "\n\nAnswer with one JSON object and nothing else, with exactly these fields: " + fields + "."
        waited = 0.0
        for attempt in range(6):
            body = {"model": model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": message}]}
            if self.send_temperature:
                body["temperature"] = 0
            if self.format == "json_schema":
                body["response_format"] = {"type": "json_schema", "json_schema": {"name": "verdict", "strict": True, "schema": schema}}
            elif self.format == "json_object":
                body["response_format"] = {"type": "json_object"}
            self._pace()
            try:
                status, data, headers = self._post(body)
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                if attempt < 1:
                    time.sleep(3)
                    continue
                raise JudgeUnavailable(f"Could not reach {self.cfg['base_url']} ({e}). Check the internet connection, "
                                       f"a firewall or proxy, and EVAL_JUDGE_BASE_URL.") from e
            err = data.get("error") if isinstance(data, dict) else None
            msg = (err.get("message") if isinstance(err, dict) else str(err or "")) or ""
            if isinstance(data, list) and data and isinstance(data[0], dict):      # Gemini wraps errors in a list
                msg = str((data[0].get("error") or {}).get("message", ""))
            low = msg.lower()
            if status == 200:
                break
            if status in (401, 403) or (status == 400 and ("api key" in low or "api_key" in low)):
                raise JudgeUnavailable(f"The {self.cfg['provider']} key was refused ({status}): {msg[:200]}")
            if status == 404:
                raise JudgeUnavailable(f"Model {model!r} or the endpoint was not found at {self.cfg['base_url']}: {msg[:200]}")
            if status == 400 and self.format != "text" and ("response_format" in low or "json_schema" in low or "json mode" in low or "schema" in low):
                self.format = "json_object" if self.format == "json_schema" else "text"
                continue
            if status == 400 and self.send_temperature and "temperature" in low:
                self.send_temperature = False
                continue
            if status == 413 or "too large" in low or "context length" in low or "maximum context" in low or "tokens_limit" in low:
                return {"verdict": None, "error": "the message is larger than this model accepts; lower EVAL_JUDGE_MAX_INPUT_CHARS",
                        "input_tokens": 0, "output_tokens": 0}
            if status == 429:
                retry = headers.get("retry-after") or headers.get("Retry-After") or ""
                m = re.search(r"(?:retry|try again) in ([\d.]+)\s*s", low)
                seconds = float(retry) if retry.replace(".", "", 1).isdigit() else (float(m.group(1)) if m else 20.0 * (attempt + 1))
                if seconds > 150 or "per day" in low or "daily" in low or "perday" in low.replace("_", "").replace(" ", "") or waited > 240:
                    raise JudgeQuotaReached(f"{self.cfg['provider']} says the free allowance is used up for now: {msg[:200]}")
                time.sleep(seconds + 1)
                waited += seconds
                continue
            if status >= 500 and attempt < 3:
                time.sleep(5 * (attempt + 1))
                continue
            return {"verdict": None, "error": f"{self.cfg['provider']} error {status}: {msg[:200]}", "input_tokens": 0, "output_tokens": 0}
        else:
            raise JudgeQuotaReached(f"{self.cfg['provider']} kept refusing requests (rate limit). Try again later.")
        usage = data.get("usage") or {}
        tokens = {"input_tokens": usage.get("prompt_tokens") or 0, "output_tokens": usage.get("completion_tokens") or 0}
        try:
            text = data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError):
            return {"verdict": None, "error": "the answer had no content", **tokens}
        m = re.search(r"\{.*\}", text, re.S)
        try:
            verdict = json.loads(m.group(0) if m else text)
        except json.JSONDecodeError:
            return {"verdict": None, "error": "the answer was not valid JSON", **tokens}
        problem = validate(verdict, schema)
        if problem:
            return {"verdict": None, "error": f"the answer did not follow the format: {problem}", **tokens}
        return {"verdict": {k: verdict[k] for k in schema["properties"]}, "error": None, **tokens}
