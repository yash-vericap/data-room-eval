"""The chain of models: moving on when one is busy or used up, the parallel check, and the settings."""
import pytest

from eval import judge, providers
from eval import reality_check as rc

from conftest import _local_model
from fakes import _cfg, _Answers, _Endpoint, _serve


def test_the_chain_moves_on_when_a_model_is_busy_or_used_up():
    busy, used_up, works = (_Answers(providers.ModelBusy("overloaded", 60)), _Answers(providers.JudgeQuotaReached("daily")),
                            _Answers("ok"))
    fb = providers.FallbackClient([_cfg("a"), _cfg("b"), _cfg("c")], clients=[busy, used_up, works])
    out = fb.complete("ignored", "s", "m", {})
    assert out["model"] == "c" and out["verdict"] == {"answer": "c"} and len(fb.events) == 2
    assert fb.complete("ignored", "s", "m", {})["model"] == "c" and (busy.calls, used_up.calls) == (1, 1)  # both still resting
    fb.entries[0]["until"] = 0                                                       # the first model's rest is over
    busy.outcomes = ["ok"]
    assert fb.complete("ignored", "s", "m", {})["model"] == "a"                     # it comes back first
    assert [u["answers"] for u in fb.usage()] == [1, 0, 2]

    gone = providers.FallbackClient([_cfg("a"), _cfg("b")], clients=[_Answers(providers.JudgeUnavailable("unknown model")),
                                                                     _Answers(providers.JudgeUnavailable("key refused"))])
    with pytest.raises(providers.JudgeUnavailable, match="No model in the chain"):
        gone.complete("x", "s", "m", {})
    tired = providers.FallbackClient([_cfg("a")], clients=[_Answers(providers.JudgeQuotaReached("daily"))])
    with pytest.raises(providers.JudgeQuotaReached, match="Every model in the chain"):
        tired.complete("x", "s", "m", {})


def test_warm_up_finds_the_busy_models_at_once(monkeypatch):
    answers = {"a": providers.ModelBusy("overloaded", 120), "b": providers.JudgeQuotaReached("daily"),
               "c": providers.JudgeUnavailable("retired"), "d": "ok"}

    def fake(self, model, system, message, schema):
        if isinstance(answers[model], Exception):
            raise answers[model]
        return {"verdict": {"answer": "ok"}, "error": None, "input_tokens": 1, "output_tokens": 1}
    monkeypatch.setattr(providers.ChatClient, "complete", fake)
    fb = providers.FallbackClient([_cfg(m) for m in "abcd"])
    seen = []
    fb.on_event = seen.append
    states = {u["model"]: u["state"] for u in fb.warm_up()}
    assert states["a"].startswith("resting") and states["b"].startswith("resting") and states["c"].startswith("dropped")
    assert states["d"] == "ready" and len(seen) == 3
    assert fb.complete("x", "s", "m", {})["model"] == "d"          # straight to the one that answers
    assert fb.warm_up() == fb.usage()                                # not asked again within ten minutes


def test_chain_settings_and_a_busy_model_is_given_up_quickly(tmp_path, monkeypatch):
    _local_model(monkeypatch)
    for k in ("EVAL_JUDGE_PROVIDER", "EVAL_JUDGE_BASE_URL", "EVAL_JUDGE_API_KEY", "EVAL_JUDGE_MODEL"):
        monkeypatch.delenv(k)
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    monkeypatch.setenv("EVAL_JUDGE_CHAIN", "gemini-flash-latest, gemini:gemini-3.1-flash-lite, github:openai/gpt-4.1-mini")
    cfg = providers.settings()
    assert "free tier" in cfg["problem"]                                  # strict: nothing is trusted yet
    monkeypatch.setenv("EVAL_TRUSTED_PROVIDERS", "gemini")
    cfg = providers.settings()
    assert [c["model"] for c in cfg["chain"]] == ["gemini-flash-latest", "gemini-3.1-flash-lite"] and cfg["problem"] is None
    assert len(cfg["skipped"]) == 1 and "github" in cfg["skipped"][0]   # no token, and not trusted
    assert isinstance(judge._client(), providers.FallbackClient) and "then gemini-3.1-flash-lite" in judge.judge_label()

    server = _serve(monkeypatch, tmp_path, [(503, {"error": {"message": "This model is currently experiencing high demand."}}, {})])
    client = providers.ChatClient(providers.settings(), fail_fast=True)
    with pytest.raises(providers.ModelBusy, match="overloaded"):
        client.complete("stand-in", "s", "u", rc.SCHEMA_LEFTOVER)
    server.shutdown()
    assert len(_Endpoint.seen) >= 1
