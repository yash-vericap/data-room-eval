"""The Vericap run check: one run of our own system against the ground truth and the documents.

The run does not have to follow the output contract. read_findings() finds the list of findings in any
JSON shape and reads each one leniently. The check then has two steps, each one model call per item:

1. Every ground-truth case against the run: Found, Partially found or Missed for a reportable case;
   Not flagged, Labelled correctly or Wrongly flagged for a non-issue case.
2. Every finding that maps to no case against the documents: a real issue the ground truth does not
   have, a known change, not a discrepancy, or not in the documents. The rule gate (eval/context.py)
   then rejects what the rules exclude, so a reviewer only sees findings that could matter.

Safeguards: every verdict must quote a passage, and the quote is checked by rule against what the model
was shown; finding IDs and rule IDs are checked against the real lists; the model can never add a case
or change a label. A manual verdict always wins over the model's.

Every verdict is saved the moment it exists (reality_checks/<check_id>.json), so a check stopped by a
provider limit loses nothing and carries on when run again."""
from __future__ import annotations

from .baselines import as_contract_run, baseline_comparison, pages_sent  # noqa: F401
from .candidates import (accept_candidate, checklist, closest_cases, prefill_case, reject_candidate,  # noqa: F401
                         restore, seen_by_baselines)
from .fields import _classification, _doc_id, _severity  # noqa: F401
from .labels import *  # noqa: F401,F403
from .messages import (CASE_LEVELS, _finding_full, case_message, focused, leftover_message, min_relevance,  # noqa: F401
                       rank_findings)
from .pages import _page_of, _pages_block  # noqa: F401
from .prompts import SCHEMA_LEFTOVER, SCHEMA_NON_ISSUE, SCHEMA_REPORTABLE, SYSTEM  # noqa: F401
from .reader import read_findings  # noqa: F401
from .report import markdown  # noqa: F401
from .results import finding_band, results, verdict_sentence  # noqa: F401
from .runner import run_check  # noqa: F401
from .state import added_since, case_verdict, linked, models_used, remaining, scope  # noqa: F401
from .storage import check_id, checks_dir, clear_manual, delete_check, list_checks, load_check, open_check, save, set_manual  # noqa: F401
from .verdicts import case_hash, judge_case, judge_leftover, own_quotes  # noqa: F401



