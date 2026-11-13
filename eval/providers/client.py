"""One OpenAI-style /chat/completions endpoint: pacing, retries, and the answer checked against its format."""
from __future__ import annotations

import json
import re
import ssl
import threading
import time
import urllib.error
import urllib.request

from .policy import JudgeQuotaReached, JudgeUnavailable, ModelBusy, allowed_hosts, check_request
from .settings import validate


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

    def __init__(self, cfg: dict, fail_fast: bool = False, timeout: float | None = None):
        self.cfg = cfg
        self.fail_fast = fail_fast        # in a chain: give up quickly on a busy model, so the next one can answer
        self.timeout = timeout or (60 if fail_fast else 180)
        self.format = "json_schema"       # falls back to json_object, then to plain text, if the provider refuses
        self.send_temperature = True
        self._lock, self._last = threading.Lock(), float("-inf")     # no wait before the first request

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
            with urllib.request.urlopen(req, timeout=self.timeout, context=_ssl_context() if url.startswith("https") else None) as resp:
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
                slow = isinstance(e, TimeoutError) or "timed out" in str(e).lower()
                if self.fail_fast and slow:
                    raise ModelBusy(f"{model} did not answer within {self.timeout:.0f} seconds", 180) from e
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
                daily = "per day" in low or "daily" in low or "perday" in low.replace("_", "").replace(" ", "")
                if seconds > 150 or daily or waited > 240:
                    raise JudgeQuotaReached(f"{self.cfg['provider']} says the free allowance of {model} is used up for now: {msg[:200]}")
                if self.fail_fast and seconds > 10:
                    raise ModelBusy(f"{model} is rate-limited: {msg[:120]}", seconds)
                time.sleep(seconds + 1)
                waited += seconds
                continue
            if status >= 500 and self.fail_fast:
                raise ModelBusy(f"{model} is overloaded ({status}): {msg[:120]}", 120)
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
