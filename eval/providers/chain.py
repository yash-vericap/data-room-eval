"""Several models tried in order, so a check carries on when one is busy or used up."""
from __future__ import annotations

import threading
import time

from .client import ChatClient
from .policy import JudgeQuotaReached, JudgeUnavailable, ModelBusy
from .settings import settings


class FallbackClient:
    """Several models, tried in order. A model that is busy or rate-limited rests for a while and the next
    one answers; a model whose allowance is used up rests for an hour; a model that cannot be used at all
    (unknown, refused key) is dropped. The first model comes back as soon as its rest is over.

    complete() returns what ChatClient.complete() returns, plus "model" and "provider" (the one that
    answered). It raises JudgeQuotaReached when every model is resting for longer than max_wait seconds,
    and JudgeUnavailable when none can be used at all. `events` lists every switch, for the screen."""

    def __init__(self, cfgs: list[dict], clients: list | None = None, max_wait: float = 90.0):
        if not cfgs:
            raise JudgeUnavailable("The model chain is empty.")
        clients = clients or [ChatClient(c, fail_fast=len(cfgs) > 1) for c in cfgs]
        self.entries = [{"cfg": c, "client": k, "until": 0.0, "dead": None, "answers": 0} for c, k in zip(cfgs, clients)]
        self.max_wait, self.events = max_wait, []
        self.on_event = None              # called with each event's text, so a screen can show it as it happens
        self.warmed_at = None             # when the models were last asked all at once
        self._lock = threading.Lock()

    def _note(self, entry: dict, text: str) -> None:
        line = f"{time.strftime('%H:%M:%S')} {entry['cfg']['model']}: {text}"
        self.events.append(line)
        if self.on_event:
            try:
                self.on_event(line)
            except Exception:             # a screen that cannot be updated must not stop the check
                pass

    def warm_up(self, timeout: float = 20.0, max_age: float = 600.0) -> list[dict]:
        """Asks every model a one-word question at the same time, so the busy and used-up ones are found in
        seconds instead of one after another at the start of a run. Skipped when done in the last max_age
        seconds. Returns usage()."""
        if self.warmed_at is not None and time.monotonic() - self.warmed_at < max_age:
            return self.usage()
        probe = {"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"], "additionalProperties": False}
        now = time.monotonic()
        todo = [e for e in self.entries if not e["dead"] and e["until"] <= now]

        def ask(entry):
            client = ChatClient(entry["cfg"], fail_fast=True, timeout=timeout)
            try:
                client.complete(entry["cfg"]["model"], "You check that a model answers.", "Reply with ok in the answer field.", probe)
                return entry, None, 0.0
            except ModelBusy as e:
                return entry, f"busy, resting {e.seconds:.0f} s ({e})", e.seconds
            except JudgeQuotaReached as e:
                return entry, f"allowance used up, resting an hour ({e})", 3600.0
            except JudgeUnavailable as e:
                return entry, f"dropped ({e})", -1.0

        if todo:
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=len(todo)) as pool:
                for entry, problem, rest in pool.map(ask, todo):
                    if problem is None:
                        continue
                    with self._lock:
                        if rest < 0:
                            entry["dead"] = problem[:200]
                        else:
                            entry["until"] = time.monotonic() + rest
                    self._note(entry, problem)
        self.warmed_at = time.monotonic()
        return self.usage()

    def complete(self, model: str, system: str, message: str, schema: dict) -> dict:
        while True:
            with self._lock:
                now = time.monotonic()
                live = [e for e in self.entries if not e["dead"]]
                if not live:
                    raise JudgeUnavailable("No model in the chain can be used: " + "; ".join(
                        f"{e['cfg']['model']} ({e['dead']})" for e in self.entries))
                ready = [e for e in live if e["until"] <= now]
                wait = 0.0 if ready else min(e["until"] for e in live) - now
            if not ready:
                if wait > self.max_wait:
                    raise JudgeQuotaReached("Every model in the chain is busy or used up for now. Everything done so far "
                                            "is saved; run the check again later, or add models to EVAL_JUDGE_CHAIN.")
                time.sleep(wait)
                continue
            entry = ready[0]
            if self.on_event:
                self._note(entry, "asking")
            try:
                out = entry["client"].complete(entry["cfg"]["model"], system, message, schema)
            except ModelBusy as e:
                with self._lock:
                    entry["until"] = time.monotonic() + e.seconds
                self._note(entry, f"busy, resting {e.seconds:.0f} s ({e})")
                continue
            except JudgeQuotaReached as e:
                with self._lock:
                    entry["until"] = time.monotonic() + 3600
                self._note(entry, f"allowance used up, resting an hour ({e})")
                continue
            except JudgeUnavailable as e:
                with self._lock:
                    entry["dead"] = str(e)[:200]
                self._note(entry, f"dropped ({e})")
                continue
            entry["answers"] += 1
            return {**out, "model": entry["cfg"]["model"], "provider": entry["cfg"]["provider"]}

    def usage(self) -> list[dict]:
        """How many answers each model gave, and its state now."""
        now = time.monotonic()
        return [{"model": e["cfg"]["model"], "provider": e["cfg"]["provider"], "answers": e["answers"],
                 "state": f"dropped: {e['dead']}" if e["dead"] else
                 f"resting {e['until'] - now:.0f} s" if e["until"] > now else "ready"} for e in self.entries]


_CLIENTS: dict[tuple, object] = {}


def make_client(cfg: dict | None = None):
    """The client for the model settings in force: a FallbackClient when the chain has more than one model.
    The same client is reused while the settings stay the same, so a model found busy or used up keeps
    resting across checks instead of being tried again (and waited for) at the start of every run."""
    cfg = cfg or settings()
    if cfg["problem"]:
        raise JudgeUnavailable(cfg["problem"])
    chain = cfg.get("chain") or [cfg]
    key = tuple((c["provider"], c["model"], c["base_url"], c["key"], c["rpm"]) for c in chain)
    if key not in _CLIENTS:
        _CLIENTS.clear()
        _CLIENTS[key] = FallbackClient(chain) if len(chain) > 1 else ChatClient(chain[0])
    return _CLIENTS[key]


def reset_clients() -> None:
    """Forgets every rest and pause, so the whole chain is tried again from the top."""
    _CLIENTS.clear()
