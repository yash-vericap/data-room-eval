"""The data policy, the request checks, the client's handling of each answer, and the chain of models."""

import pytest

from eval import judge, providers
from eval import reality_check as rc

from conftest import _local_model
from fakes import _Endpoint, _ok, _serve
from helpers import F_CREDIT, CASES, _check


def test_data_policy_and_no_tools(monkeypatch):
    _local_model(monkeypatch)
    assert providers.settings()["problem"] is None                         # a model on this machine is allowed
    monkeypatch.delenv("EVAL_JUDGE_PROVIDER")
    monkeypatch.delenv("EVAL_JUDGE_BASE_URL")
    monkeypatch.setenv("GITHUB_MODELS_TOKEN", "t")
    cfg = providers.settings()
    assert cfg["provider"] == "github" and "strict" in cfg["problem"] and "free tier" in cfg["problem"]
    with pytest.raises(providers.JudgeUnavailable, match="strict"):
        judge._client()
    monkeypatch.setenv("EVAL_TRUSTED_PROVIDERS", "github")
    assert providers.settings()["problem"] is None
    monkeypatch.delenv("EVAL_TRUSTED_PROVIDERS")
    monkeypatch.setenv("EVAL_JUDGE_PROVIDER", "custom")
    monkeypatch.setenv("EVAL_JUDGE_BASE_URL", "https://api.example.com/v1")
    assert "strict" in providers.settings()["problem"]
    monkeypatch.setenv("EVAL_JUDGE_PROVIDER", "local")
    assert "not this machine" in providers.settings()["problem"]

    with pytest.raises(providers.JudgeUnavailable, match="never given tools"):
        providers.check_request("http://127.0.0.1:9/chat/completions", {"model": "m", "tools": []}, ["127.0.0.1"])
    with pytest.raises(providers.JudgeUnavailable, match="not an allowed host"):
        providers.check_request("https://elsewhere.example/chat/completions", {"model": "m"}, ["127.0.0.1"])


def test_requests_carry_no_tools_and_stay_on_the_allowed_host(tmp_path, monkeypatch, empty):
    server = _serve(monkeypatch, tmp_path, [_ok({"status": "missed", "finding_ids": [], "covered": "", "missing": "",
                                                 "quote": "", "explanation": "e"})])
    _Endpoint.seen.clear()
    check = _check([F_CREDIT])
    try:
        rc.run_check(check, [CASES[0]], workers=1)
    except providers.JudgeUnavailable:
        pass                                                    # the stand-in answers every call with a case verdict
    server.shutdown()
    assert _Endpoint.seen and all(not (providers.FORBIDDEN_KEYS & set(b)) and len(b["messages"]) == 2 for b in _Endpoint.seen)
    assert check["case_verdicts"]["T1-001"]["sent"]["provider"] == "custom"
    monkeypatch.setenv("EVAL_ALLOWED_HOSTS", "models.example.com")
    with pytest.raises(providers.JudgeUnavailable, match="not an allowed host"):
        providers.ChatClient(providers.settings()).complete("m", "s", "u", rc.SCHEMA_LEFTOVER)


SCHEMA = {"type": "object", "properties": {"answer": {"type": "string", "enum": ["ok", "no"]}}, "required": ["answer"],
          "additionalProperties": False}


def test_client_falls_back_when_schema_mode_is_refused_and_checks_the_format(tmp_path, monkeypatch, local_model):
    refuse = lambda body: ((400, {"error": {"message": "response_format json_schema is not supported"}}, {})
                           if body.get("response_format", {}).get("type") == "json_schema" else _ok({"answer": "ok"}))
    server = _serve(monkeypatch, tmp_path, [refuse])
    client = providers.ChatClient(providers.settings())
    out = client.complete("free-gpt", "s", "m", SCHEMA)
    assert out["verdict"] == {"answer": "ok"} and out["input_tokens"] == 900
    assert _Endpoint.seen[0]["temperature"] == 0 and _Endpoint.seen[-1]["response_format"]["type"] == "json_object"
    _Endpoint.plan = [_ok({"answer": "maybe"})]
    assert "did not follow the format" in client.complete("free-gpt", "s", "m", SCHEMA)["error"]
    server.shutdown()


def test_client_limits_and_refused_keys(tmp_path, monkeypatch, local_model):
    server = _serve(monkeypatch, tmp_path, [(429, {"error": {"message": "slow down"}}, {"Retry-After": "0"}), _ok({"answer": "ok"})])
    client = providers.ChatClient(providers.settings())
    assert client.complete("free-gpt", "s", "m", SCHEMA)["verdict"] == {"answer": "ok"}          # a short wait is waited out
    _Endpoint.plan = [(429, {"error": {"message": "Rate limit reached: requests per day"}}, {"Retry-After": "40000"})]
    with pytest.raises(providers.JudgeQuotaReached, match="used up"):
        client.complete("free-gpt", "s", "m", SCHEMA)
    _Endpoint.plan = [(401, {"error": {"message": "bad token"}}, {})]
    with pytest.raises(providers.JudgeUnavailable, match="refused"):
        client.complete("free-gpt", "s", "m", SCHEMA)
    server.shutdown()
