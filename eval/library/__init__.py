"""Keeping the answer key up to date: the sheet upload, the working draft, snapshots and the change log.

The evaluation sheet stays the place where cases, facts, documents, rules and baseline runs are written.
This module loads its export in three steps, so nothing is written by accident:

    staged = stage(read(file))          parse every tab into memory
    problems = validate(staged)         blocking errors and warnings
    changes = preview(staged)           what is new, changed and removed, field by field
    apply(staged, file_name, note)      write, and log every changed object

It also holds what lives between two uploads:
- answer_key/library_draft.json       the working draft (uploads and accepted candidates write here)
- answer_key/library_vN.json          frozen snapshots, never changed after freeze()
- answer_key/pending.json             accepted candidates and correction requests not yet in the sheet
- answer_key/rejected_candidates.json findings the evaluator rejected, so they are not reviewed twice
- answer_key/changelog.json           one entry per change, with its reason"""
from __future__ import annotations

from .apply import apply  # noqa: F401
from .changes import (add_correction, add_pending_case, add_rejected,  # noqa: F401
                      draft_differs, ensure_draft, freeze, load_changelog, load_pending, load_rejected, log, log_many,
                      next_case_id)
from .columns import ACCEPTED, CORRECTION, REJECT_REASONS, CASE_SKIP, DOC_COLUMNS, FACT_COLUMNS, FINDING_COLUMNS, GT_COLUMNS, RULE_COLUMNS, RUN_COLUMNS, TABS  # noqa: F401
from .diffing import _plain, current, diff, preview  # noqa: F401
from .sheets import case_row, pending_xlsx, template_xlsx  # noqa: F401
from .staging import build_documents, build_facts, build_rules, read, stage  # noqa: F401
from .validate import validate  # noqa: F401



