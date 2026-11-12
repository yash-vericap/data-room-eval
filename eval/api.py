"""A small HTTP endpoint so the discrepancy checker can send a run straight to the tool.

    python -m eval serve --port 8000

POST /runs      body: one run in the contract format. The run is checked, stored and scored.
GET  /runs      scores of every stored run.
GET  /health

What comes back never shows withheld cases. The sender gets the overall scores, the contract
problems, and case-by-case results for the development set only. If the environment variable
EVAL_API_KEY is set, requests must carry the same value in the X-API-Key header.
"""
from __future__ import annotations

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import contract, judge, report, scoring, store

PUBLIC_METRICS = ["findings", "reportable", "found", "recall", "weighted_recall", "critical_missed", "precision",
                  "false_positives", "class_accuracy", "severity_accuracy", "evidence_sufficient", "needs_review",
                  "false_positive_candidates", "duration_minutes", "cost_usd"]


def public_view(res: dict) -> dict:
    m = res["metrics"]
    dev_ids = {c["case_id"] for c in res["cases"] if c["set"] == "Development"}
    return {
        "run_id": res["run"]["run_id"], "data_room": res["run"]["data_room"],
        "scores_withheld_set": {k: m[k] for k in PUBLIC_METRICS},
        "scores_development_set": {k: m["development"][k] for k in ("reportable", "found", "recall", "weighted_recall")},
        "development_cases": [{k: c[k] for k in ("case_id", "expected_class", "expected_severity", "report", "outcome",
                                                 "finding_id", "class", "severity", "class_correct", "severity_correct")}
                              for c in res["cases"] if c["case_id"] in dev_ids],
        "contract_problems": res["problems"],
    }


def _judge(run: dict) -> str:
    try:
        out = judge.judge_run(run)
        report.write()
        text = f"{out['judged']} findings judged, {out['needs_manual']} for manual review, {out['cost']}"
        return f"stopped early ({out['left']} findings left): {out['stopped']}. {text}" if out["stopped"] else f"done: {text}"
    except judge.JudgeUnavailable as e:
        return f"not run: {e}"


def submit(payload: dict, allow_problems: bool = False, run_judge: bool | None = None,
           background: bool = False) -> tuple[int, dict]:
    """Shared by the endpoint, the command line and the app. Returns (HTTP status, response).

    run_judge: True or False, or None to run the judge whenever the GitHub Models token is present
    (switch that off with EVAL_JUDGE_ON_SUBMIT=0). background=True starts the judge and returns at once."""
    run, problems = contract.normalise(payload)
    if not run["run"]["run_id"] or not run["run"]["data_room"]:
        return 400, {"accepted": False, "contract_problems": problems}
    rooms = {c["data_room"] for c in store.load_cases()}
    if run["run"]["data_room"] not in rooms:
        return 400, {"accepted": False, "contract_problems": problems + [
            f"No answer key for data room {run['run']['data_room']!r}. Known data rooms: {sorted(rooms)}."]}
    path, problems = store.save_submission(payload, allow_problems=allow_problems)
    if path is None:
        return 422, {"accepted": False, "contract_problems": problems,
                     "message": "Rejected: the file does not follow the output contract. Nothing was stored."}
    run["problems"] = problems
    run["run"]["problems"] = problems
    res = scoring.score_run(run, store.load_cases())
    report.write()
    if run_judge is None:
        run_judge = judge.credentials_present() and os.environ.get("EVAL_JUDGE_ON_SUBMIT", "1") != "0"
    if not run_judge:
        judged = "not run" if judge.credentials_present() else f"not run: {judge.judge_label()}"
    elif background:
        threading.Thread(target=_judge, args=(run,), daemon=True).start()
        judged = "started"
    else:
        judged = _judge(run)
    return 201, {"accepted": True, "stored_as": str(path.relative_to(store.DATA)), "judge": judged, **public_view(res)}


class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, body: dict):
        data = json.dumps(body, indent=1).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _authorised(self) -> bool:
        key = os.environ.get("EVAL_API_KEY")
        return not key or self.headers.get("X-API-Key") == key

    def do_GET(self):
        if self.path.rstrip("/") == "/health":
            return self._send(200, {"ok": True})
        if not self._authorised():
            return self._send(401, {"error": "X-API-Key missing or wrong."})
        if self.path.rstrip("/") == "/runs":
            return self._send(200, {"runs": [public_view(r) for r in scoring.score_all()]})
        self._send(404, {"error": "Use POST /runs, GET /runs or GET /health."})

    def do_POST(self):
        if not self._authorised():
            return self._send(401, {"error": "X-API-Key missing or wrong."})
        if self.path.split("?")[0].rstrip("/") != "/runs":
            return self._send(404, {"error": "Use POST /runs."})
        try:
            payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        except (json.JSONDecodeError, ValueError) as e:
            return self._send(400, {"accepted": False, "contract_problems": [f"Body is not valid JSON: {e}"]})
        self._send(*submit(payload, allow_problems="allow_problems=1" in self.path, background=True))

    def log_message(self, fmt, *args):
        print("[eval api]", fmt % args)


def serve(port: int = 8000, host: str = "127.0.0.1"):
    print(f"Evaluation endpoint on http://{host}:{port}  (POST /runs)")
    ThreadingHTTPServer((host, port), Handler).serve_forever()
