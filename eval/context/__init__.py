"""The data room context layer: what is known about a data room besides its documents.

Three parts:
- the fact sheet (answer_key/facts.json): values with their status, date, source and the fact each one replaces;
- document attributes (doc_date and authority in answer_key/documents.json);
- the context rules (answer_key/context_rules.json, or DEFAULT_RULES when the file is missing).

It is used in four places: as a block of text in every check message (block_for_case, block_for_finding),
in the rule pre-check that runs before a leftover finding is judged (precheck), in the rule gate that
runs after it (gate), and in the sheet upload, which warns about cases that rest on unrecorded changes.

Everything here is rule-based and gives the same answer every time. Rules, facts and document dates are
changed in the evaluation sheet and uploaded; nothing in this module writes to them."""
from __future__ import annotations

from .blocks import block_for_case, block_for_finding, facts_for_finding  # noqa: F401
from .facts import (_src, _src_text, as_date, chain, chain_text, doc_info, load_facts, norm_values,  # noqa: F401
                    text_hash)
from .gate import decided_before, gate  # noqa: F401
from .precheck import precheck  # noqa: F401
from .rules import (ACTUAL, AUTHORITY, DEFAULT_RULES, FACT_FIELDS, FLAG_TAGS, FORECAST, RULE_FIELDS,  # noqa: F401
                    RULE_TYPES, SEVERITY_ORDER, SUBJECTS, TAG_RULE, VALUE_STATUSES, case_rules, coverage, load_rules,
                    min_candidate_severity, rule_name, rules_on)



