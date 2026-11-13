"""Scores one run against the answer key: matching, evidence checks and every metric."""
from __future__ import annotations

from .evidence import check_evidence, quote_is_real  # noqa: F401
from .runs import score_all, score_run  # noqa: F401



