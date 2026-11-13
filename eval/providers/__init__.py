"""Which model the judge runs on, and the rules on what may be sent to it.

The judge talks to one OpenAI-style chat endpoint. Three presets exist:
  github   GitHub Models (free GPT models with a GitHub account). A free tier: its terms may keep inputs.
  local    a model on this machine or a private network (for example Ollama at http://localhost:11434/v1).
  custom   another OpenAI-style endpoint, with EVAL_JUDGE_BASE_URL, EVAL_JUDGE_API_KEY and EVAL_JUDGE_MODEL.

A chain of models (EVAL_JUDGE_CHAIN) lets a check carry on when one model's free allowance runs out or it is
overloaded: the next model in the chain takes over, and the first comes back once its wait is over.

Settings, read from the environment or the .env file:
  GEMINI_API_KEY        the Google AI Studio key (preset "gemini")
  GITHUB_MODELS_TOKEN   the GitHub token (account permission "Models: Read-only")
  EVAL_JUDGE_PROVIDER   gemini | github | local | custom (when unset: the first preset whose key is present)
  EVAL_JUDGE_CHAIN      models to try in order, comma-separated, each "provider:model" or just "model" (on
                        EVAL_JUDGE_PROVIDER), for example
                        gemini:gemini-flash-latest, gemini:gemini-3.5-flash-lite, gemini:gemini-3.1-flash-lite
  EVAL_JUDGE_MODEL      model name, when the default is not wanted (required for local and custom)
  EVAL_JUDGE_RPM        most requests per minute to send
  EVAL_JUDGE_PASSES     how many times each finding is judged (default 2)
  EVAL_JUDGE_MAX_INPUT_CHARS   largest message to send; longer ones carry page excerpts instead of full pages

Data security (see the README, "Data security and storage"):
  EVAL_DATA_POLICY        strict (default) | open. Strict allows a local model, and providers named in
                          EVAL_TRUSTED_PROVIDERS. A free tier is refused unless it is allowed on purpose.
  EVAL_TRUSTED_PROVIDERS  comma-separated provider names allowed under the strict policy
  EVAL_ALLOWED_HOSTS      comma-separated hosts a request may go to (default: the configured provider's host)
No request ever carries tools, functions, MCP servers, web search or files; every body is checked before sending."""
from __future__ import annotations

from .chain import FallbackClient, make_client, reset_clients  # noqa: F401
from .client import ChatClient, _ssl_context  # noqa: F401
from .policy import (FORBIDDEN_KEYS, PRESETS, JudgeQuotaReached, JudgeUnavailable, ModelBusy,  # noqa: F401
                     _names, allowed_hosts, check_request, data_policy, is_local_host)
from .settings import chain_entries, chain_label, settings, validate  # noqa: F401



