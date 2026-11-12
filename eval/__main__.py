"""Command line.

    python -m eval score                     score every stored run, print the table, write the report
    python -m eval submit <run.json>         check one run against the contract, store it and score it
    python -m eval import-sheet <file.xlsx>  refresh the answer key and baselines from the sheet download
    python -m eval add-data-room <zip|dir>   read a data room's PDFs so quotes can be checked (--room HTC03)
    python -m eval judge [RUN_ID ...]        run the LLM judge on stored runs (all runs when none is named)
    python -m eval matcher-check             compare the automatic matcher with the manual decisions
    python -m eval serve [--port 8000]       start the HTTP endpoint for the discrepancy checker
"""
from __future__ import annotations

import argparse
import json
import sys

from . import api, compare, data_room, import_sheet, judge, report, scoring, store


def _print_scores(results):
    cols = [("Run", 22), ("Data room", 9), ("Weighted recall", 15), ("Recall", 7), ("Critical missed", 15),
            ("Precision", 9), ("False positives", 15), ("Class accuracy", 14), ("Needs review", 12)]
    print("  ".join(name.ljust(w) for name, w in cols))
    rows = sorted((report.score_row(r) for r in results), key=lambda r: (r["Data room"], -(r["Weighted recall"] or 0)))
    for r in rows:
        print("  ".join((report.pct(r[n]) if n in report.PCT_COLS else str(r[n])).ljust(w)[:w] for n, w in cols))


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m eval", description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("score")
    s = sub.add_parser("submit")
    s.add_argument("file")
    s.add_argument("--allow-problems", action="store_true", help="store the run even if it breaks the contract")
    s.add_argument("--no-judge", action="store_true", help="do not run the LLM judge on this run")
    j = sub.add_parser("judge")
    j.add_argument("run_ids", nargs="*")
    j.add_argument("--force", action="store_true", help="judge again findings that already have a verdict")
    j.add_argument("--limit", type=int, help="judge at most this many findings per run")
    j.add_argument("--model", help="override the model set in .env")
    d = sub.add_parser("add-data-room")
    d.add_argument("source")
    d.add_argument("--room")
    i = sub.add_parser("import-sheet")
    i.add_argument("file")
    sub.add_parser("matcher-check")
    v = sub.add_parser("serve")
    v.add_argument("--port", type=int, default=8000)
    v.add_argument("--host", default="127.0.0.1")
    a = p.parse_args(argv)

    if a.cmd == "score":
        results = scoring.score_all()
        _print_scores(results)
        md, csv_path = report.write(results)
        print(f"\nReport: {md}\nScores: {csv_path}")
    elif a.cmd == "submit":
        with open(a.file, encoding="utf-8") as fh:
            status, body = api.submit(json.load(fh), allow_problems=a.allow_problems,
                                      run_judge=False if a.no_judge else None)
        print(json.dumps(body, indent=1))
        return 0 if body.get("accepted") else 1
    elif a.cmd == "judge":
        runs = [r for r in store.load_runs() if not a.run_ids or r["run"]["run_id"] in a.run_ids]
        missing = set(a.run_ids) - {r["run"]["run_id"] for r in runs}
        if missing:
            print(f"No stored run named: {', '.join(sorted(missing))}")
            return 1
        cases = store.load_cases()
        print(f"Judge: {judge.judge_label()}")
        try:
            for run in runs:
                out = judge.judge_run(run, cases, model=a.model, force=a.force, limit=a.limit)
                print(f"{run['run']['run_id']}: judged {out['judged']}, already judged {out['skipped']}, "
                      f"for manual review {out['needs_manual']}, {out['cost']}")
                if out["stopped"]:
                    print(f"\nStopped: {out['stopped']}\nEverything judged so far is saved. "
                          f"Run the same command again later to continue.")
                    break
        except judge.JudgeUnavailable as e:
            print(f"The judge could not run: {e}")
            return 1
        t = judge.trust(store.load_runs(), cases, store.load_reviews(), judge.load_verdicts())
        print(f"\nJudged findings so far: {t['judged']}.")
        for label, key in [("Rules and judge pick the same case", "rules_and_judge_agree"),
                           ("Judge picks the case chosen by hand", "judge_matches_manual"),
                           ("Rules pick the case chosen by hand (same findings)", "rules_match_manual_same_findings"),
                           ("Judge gives the evidence check given by hand", "evidence_matches_manual"),
                           ("Judge gives the reasoning score given by hand", "reasoning_matches_manual")]:
            print(f"  {label}: {report.pct(t[key][0])} of {t[key][1]}")
        print(f"  Unstable between the two passes: {t['unstable']}. Sent to manual review: {t['needs_manual']}.")
        report.write()
    elif a.cmd == "add-data-room":
        try:
            data_room.add(a.source, a.room)
        except (FileNotFoundError, ValueError) as e:
            print(e)
            return 1
        report.write()
    elif a.cmd == "import-sheet":
        import_sheet.run_import(a.file)
    elif a.cmd == "matcher-check":
        res = compare.matcher_agreement(store.load_runs(), store.load_cases(), store.load_reviews())
        print(f"Same case as the manual decision: {res['same_case']} of {res['decided_by_hand']} "
              f"({report.pct(res['agreement'])})")
        for k, n in sorted(res["outcomes"].items()):
            print(f"  {k}: {n}")
        for d in res["disagreements"]:
            print(f"  {d['finding_id']}: manual {d['manual']}, rules {d['rules'] or d['rules_status']}")
    elif a.cmd == "serve":
        api.serve(a.port, a.host)
    return 0


if __name__ == "__main__":
    sys.exit(main())
