"""Matching findings to answer-key cases.

Three steps, as in the methodology:
1. Location. A case is a candidate for a finding when the finding cites at least one of the case's
   documents.
2. Content. Each candidate pair gets a score from three parts: how much of the case's cited
   documents and pages the finding covers, how many of the case's key values (amounts, dates,
   percentages, counts) appear in the finding, and how similar the wording is.
3. Manual review. Pairs between the two thresholds go to a review list. A stored manual decision
   always wins over the automatic result.

Everything here is rule-based and gives the same answer on every run."""
from __future__ import annotations

from .index import RoomIndex  # noqa: F401
from .linking import MATCH_AT, MERGE_AT, REVIEW_AT, match_run  # noqa: F401
from .text import tokens  # noqa: F401
from .values import key_values  # noqa: F401



