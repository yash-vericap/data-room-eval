"""The statuses a verdict can have, and the version of the instructions."""
from __future__ import annotations




PROMPT_VERSION = "RC-v2"
PARTIAL_CREDIT = 0.5

FOUND, PARTIAL, MISSED, REVIEW = "Found", "Partially found", "Missed", "Needs review"
NOT_FLAGGED, LABELLED, WRONG = "Not flagged", "Labelled correctly", "Wrongly flagged"
REAL, KNOWN, NOT_DISC, NOT_IN_DOCS = "Real issue, not in ground truth", "Known change", "Not a discrepancy", "Not in documents"
CASE_LABELS = {"found": FOUND, "partially_found": PARTIAL, "missed": MISSED, "cannot_decide": REVIEW,
               "wrongly_flagged": WRONG, "labelled_correctly": LABELLED, "not_flagged": NOT_FLAGGED}
NEW_LABELS = {"real_issue": REAL, "known_change": KNOWN, "not_a_discrepancy": NOT_DISC, "not_in_documents": NOT_IN_DOCS,
              "cannot_decide": REVIEW}
NEW_RAW = {v: k for k, v in NEW_LABELS.items()}
LINKING = {FOUND, PARTIAL, WRONG, LABELLED}                 # statuses that tie a finding to a case
CANDIDATE, REJECTED_RULE, REJECTED_EVALUATOR = "Candidate", "Rejected by rule", "Rejected by evaluator"
BANDS = [CANDIDATE, REVIEW, REJECTED_RULE, REJECTED_EVALUATOR]
STATUS_ORDER = [MISSED, WRONG, REVIEW, "Not checked", PARTIAL, FOUND, LABELLED, NOT_FLAGGED]
