"""What the model is told: the shared instructions, the task for each kind of call, and the answer formats."""
from __future__ import annotations

from .. import contract
from .labels import NEW_LABELS


SYSTEM = """You are an independent reviewer of an AI system that looks for discrepancies across the documents of a deal data room (US historic tax credit deals). An evaluator wrote the ground truth by hand. You compare the system's output with the ground truth and with the documents. Your verdict is used to score the system, so accuracy matters more than being agreeable: a confident, well-written finding can still be wrong or only half right.

Use only what is in the message. Do not use outside knowledge and do not assume what other documents say. When the material does not settle the question, answer "cannot_decide"; that is better than a guess. Different wording from the ground truth is fine. Sharing a document or a figure is not enough on its own: a finding covers a case only when it is about the same underlying problem.

The message may hold a data room context: known facts, the changes between them, document dates and authority, and context rules. Apply the rules as written. Read the wording of every date and figure: an estimate, target or projection is a forecast, not a fact, and a value that a dated document has replaced is no longer current."""
_QUOTE = ("quote: the passage your verdict relies on most, copied word for word from the material in the message. It is "
          "checked automatically, and a quote that is not in the message voids the verdict.")
TASK_REPORTABLE = f"""Your task: decide whether the run's findings cover the ground-truth case in the message.

status:
- found: a finding states the same problem with its essential facts: the right documents on both sides, the conflicting figures, dates or terms, and the right conclusion. Differences in wording and severity do not matter.
- partially_found: a finding is about this problem but leaves out or gets wrong an essential part: only one side of the conflict, a missing document the case rests on, a wrong figure or date, half the conclusion, or a symptom reported without its cause.
- missed: no finding is about this problem.
- cannot_decide: the material does not settle it.
finding_ids: the IDs of the findings that cover the case, exactly as written. Empty when missed.
covered: one sentence on what the run got right. Empty when missed.
missing: one sentence on what was left out or wrong. Empty when found.
{_QUOTE}
explanation: one sentence on why."""
TASK_NON_ISSUE = f"""Your task: the ground-truth case in the message is a known non-issue. The documents differ or look odd, but it must not be reported as a problem. Decide what the run did with it.

status:
- wrongly_flagged: a finding reports it as a contradiction or as missing evidence.
- labelled_correctly: a finding mentions it but calls it explained, contextual or consistent.
- not_flagged: no finding is about it.
- cannot_decide: the material does not settle it.
finding_ids: the IDs of the findings that are about this case, exactly as written. Empty when not flagged.
covered: one sentence on what the run said about it. Empty when not flagged.
missing: one sentence on what the run got wrong. Empty when it was right.
{_QUOTE}
explanation: one sentence on why."""
TASK_LEFTOVER = """Your task: the finding in the message maps to no ground-truth case. Decide from the document pages whether it is a real issue.

status:
- real_issue: the pages show a genuine discrepancy, or genuinely missing evidence, as the finding says.
- known_change: the difference is a change the data room records (an amendment, a repricing, a rate reset, a signed change order), or two forecasts that moved, so the context rules say it is not a discrepancy.
- not_a_discrepancy: the figures or passages exist, but they agree, or the difference is explained in another way such as a different basis, phase or unit.
- not_in_documents: the figures, quotes or claims cannot be found in the pages, or the pages say something else.
- cannot_decide: the pages do not settle it.
rule_ids: the IDs of the context rules your verdict relies on, for example C1. Empty when none applies.
fact_or_judgment: "fact" when the issue can be checked against the documents, "judgment" when it rests on opinion.
why_it_matters: one sentence on what goes wrong for the customer or investor if this is real. Empty when it is not real.
why_it_might_not: one sentence giving the strongest reason this may not belong in the ground truth. Empty when there is none.
severity: Critical, High, Medium or Low for a real issue, otherwise not_applicable.
quote: a passage copied word for word from the pages that your verdict rests on, or empty when the pages hold nothing relevant.
explanation: one sentence on why.
A rule pre-check result may be shown. It comes from fixed rules and the fact sheet; you may disagree with it."""


def _schema(statuses: list[str]) -> dict:
    props = {"status": {"type": "string", "enum": statuses}, "finding_ids": {"type": "array", "items": {"type": "string"}},
             "covered": {"type": "string"}, "missing": {"type": "string"}, "quote": {"type": "string"},
             "explanation": {"type": "string"}}
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


SCHEMA_REPORTABLE = _schema(["found", "partially_found", "missed", "cannot_decide"])
SCHEMA_NON_ISSUE = _schema(["wrongly_flagged", "labelled_correctly", "not_flagged", "cannot_decide"])
_NEW_PROPS = {
    "status": {"type": "string", "enum": list(NEW_LABELS)}, "rule_ids": {"type": "array", "items": {"type": "string"}},
    "fact_or_judgment": {"type": "string", "enum": ["fact", "judgment"]}, "why_it_matters": {"type": "string"},
    "why_it_might_not": {"type": "string"},
    "severity": {"type": "string", "enum": contract.SEVERITIES + ["not_applicable"]},
    "quote": {"type": "string"}, "explanation": {"type": "string"}}
SCHEMA_LEFTOVER = {"type": "object", "properties": _NEW_PROPS, "required": list(_NEW_PROPS), "additionalProperties": False}
