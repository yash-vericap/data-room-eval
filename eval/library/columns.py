"""The tabs and columns of the evaluation sheet, and the labels the answer-key changes use."""
from __future__ import annotations




GT_COLUMNS = ["Case ID", "Classification", "Severity", "Weight", "Summary", "Claims compared", "Citations", "Explanation",
              "Report", "Check type", "Set", "Data room", "Documents", "Register IDs", "Fact or judgment", "Ambiguous",
              "Alternative readings", "Open questions", "Scenario tags", "Snapshot", "Review status", "Last change"]
DOC_COLUMNS = ["Document ID", "Data room", "Title", "Document type", "Role", "Status", "Format", "Pages", "Document date",
               "Authority"]
FACT_COLUMNS = ["Fact ID", "Data room", "Subject", "Scope", "Value", "Unit or basis", "Value status", "As of", "Source",
                "Supersedes", "Change reason", "Change source", "Notes"]
RULE_COLUMNS = ["Rule ID", "Name", "Rule", "Type", "Expected class", "Critical", "On", "Notes"]
RUN_COLUMNS = ["Run ID", "Model or version", "Data room", "Prompt version", "Run number", "Run date", "Access route",
               "Time (minutes)", "Format repairs", "Source"]
FINDING_COLUMNS = ["Finding ID", "Classification", "Severity", "Weight", "Summary", "Claims compared", "Citations",
                   "Explanation", "Run ID", "Confidence", "Matched case ID", "Match status", "Format repaired",
                   "Reviewer note", "Expected classification", "Case reportable", "Case weight", "Case severity",
                   "Case set", "Evidence check", "Reasoning score"]
TABS = {"Ground Truth": GT_COLUMNS, "Documents": DOC_COLUMNS, "Fact Sheet": FACT_COLUMNS, "Context Rules": RULE_COLUMNS,
        "Baseline Runs": RUN_COLUMNS, "Baseline Findings": FINDING_COLUMNS, "Severity Weights": ["Severity", "Weight"]}
CASE_SKIP = {"snapshot", "origin", "origin_check"}       # not compared between two versions of a case
ACCEPTED = "Accepted, not yet in the sheet"
CORRECTION = "Correction requested, not yet in the sheet"
REJECT_REASONS = ["Already in the ground truth", "Excused by a rule", "Not a major red flag",
                  "Not supported by the documents", "Out of scope", "Other"]
