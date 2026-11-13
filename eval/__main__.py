"""Command line.

    python -m eval score                     score every stored run by the fixed rules, print the table, write reports/
    python -m eval submit <run.json>         check one run against the contract, store it and score it
    python -m eval import-sheet <file.xlsx>  preview what the sheet download would change (add --yes to write it)
    python -m eval freeze                    freeze the working draft of the answer key as the next Library vN
    python -m eval add-data-room <zip|dir>   read a data room's PDFs so quotes can be checked (--room HTC03)
    python -m eval move-to-mongo             move the page text under data_room/ to MongoDB (--with-pdfs for the PDFs)
    python -m eval serve [--port 8000]       start the HTTP endpoint for the discrepancy checker

The Vericap run check runs in the app: streamlit run app.py
"""
from __future__ import annotations

import argparse
import json
import sys

from . import api, data_room, doc_store, import_sheet, library, report, scoring


def _print_scores(results):
    cols = [("Run", 22), ("Data room", 9), ("Weighted recall", 15), ("Recall", 7), ("Critical missed", 15),
            ("Precision", 9), ("False positives", 15), ("Class accuracy", 14), ("Needs review", 12)]
    print("  ".join(name.ljust(w) for name, w in cols))
    rows = sorted((report.score_row(r) for r in results), key=lambda r: (r["Data room"], -(r["Weighted recall"] or 0)))
    for r in rows:
        print("  ".join((report.pct(r[n]) if n in report.PCT_COLS else str(r[n])).ljust(w)[:w] for n, w in cols))


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m eval", description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("score")
    s = sub.add_parser("submit")
    s.add_argument("file")
    s.add_argument("--allow-problems", action="store_true", help="store the run even if it breaks the contract")
    d = sub.add_parser("add-data-room")
    d.add_argument("source")
    d.add_argument("--room")
    d.add_argument("--keep-local", action="store_true", help="keep the local copies even when MongoDB holds a verified copy")
    mv = sub.add_parser("move-to-mongo")
    mv.add_argument("--rooms", nargs="*", help="data rooms to move (default: every room under data_room/)")
    mv.add_argument("--with-pdfs", action="store_true", help="store the PDFs as well as the page text")
    mv.add_argument("--keep-local", action="store_true", help="do not delete the local folder after the copy is verified")
    i = sub.add_parser("import-sheet")
    i.add_argument("file")
    i.add_argument("--yes", action="store_true", help="write the changes; without it only the preview is printed")
    i.add_argument("--note", default="", help="a note for the change log")
    z = sub.add_parser("freeze")
    z.add_argument("--reason", default="", help="why the working draft is frozen now")
    v = sub.add_parser("serve")
    v.add_argument("--port", type=int, default=8000)
    v.add_argument("--host", default="127.0.0.1")
    return p


def main(argv=None) -> int:
    a = _parser().parse_args(argv)
    if a.cmd == "score":
        results = scoring.score_all()
        _print_scores(results)
        md, csv_path = report.write(results)
        print(f"\nReport: {md}\nScores: {csv_path}")
    elif a.cmd == "submit":
        with open(a.file, encoding="utf-8") as fh:
            status, body = api.submit(json.load(fh), allow_problems=a.allow_problems)
        print(json.dumps(body, indent=1))
        return 0 if body.get("accepted") else 1
    elif a.cmd == "add-data-room":
        try:
            data_room.add(a.source, a.room, keep_local=a.keep_local)
        except (FileNotFoundError, ValueError) as e:
            print(e)
            return 1
    elif a.cmd == "move-to-mongo":
        try:
            rows = data_room.move_to_mongo(a.rooms, with_pdfs=a.with_pdfs or doc_store.store_pdfs(), keep_local=a.keep_local)
        except doc_store.StoreUnavailable as e:
            print(e)
            return 1
        if not rows:
            print("No data room with page text was found under data_room/.")
        return 1 if any(not r["verified"] for r in rows) else 0
    elif a.cmd == "import-sheet":
        out = import_sheet.run_import(a.file, write=a.yes, note=a.note)
        return 1 if out["errors"] else 0
    elif a.cmd == "freeze":
        res = library.freeze(a.reason)
        print(f"Frozen as {res['name']}: {res['cases']} cases."
              + (f" {res['pending']} accepted cases are not in the sheet yet." if res["pending"] else ""))
    elif a.cmd == "serve":
        api.serve(a.port, a.host)
    return 0


if __name__ == "__main__":
    sys.exit(main())
