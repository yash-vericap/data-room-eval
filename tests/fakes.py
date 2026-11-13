"""Stand-ins for outside services: an OpenAI-style endpoint on this machine, chained models, small PDFs."""
import json as _json
import threading as _threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from eval import store


class _Endpoint(BaseHTTPRequestHandler):
    plan, seen = [], []          # plan: what to answer, in order; the last entry repeats

    def do_POST(self):
        body = _json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        type(self).seen.append(body)
        step = self.plan.pop(0) if len(self.plan) > 1 else self.plan[0]
        status, payload, headers = step(body) if callable(step) else step
        data = _json.dumps(payload).encode()
        self.send_response(status)
        for k, v in headers.items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


def _ok(v):
    return (200, {"choices": [{"message": {"content": "```json\n" + _json.dumps(v) + "\n```"}}],
                  "usage": {"prompt_tokens": 900, "completion_tokens": 80}}, {})


def _serve(monkeypatch, tmp_path, plan):
    _Endpoint.plan, _Endpoint.seen = list(plan), []
    server = HTTPServer(("127.0.0.1", 0), _Endpoint)
    _threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setenv("EVAL_JUDGE_PROVIDER", "custom")
    monkeypatch.setenv("EVAL_JUDGE_BASE_URL", f"http://127.0.0.1:{server.server_port}")
    monkeypatch.setenv("EVAL_JUDGE_API_KEY", "k")
    monkeypatch.setenv("EVAL_JUDGE_MODEL", "free-gpt")
    monkeypatch.setenv("EVAL_JUDGE_RPM", "6000")
    return server


def _cfg(model):
    return {"provider": "custom", "model": model, "key": "k", "base_url": "http://127.0.0.1:9", "rpm": 0}


class _Answers:
    def __init__(self, *outcomes):
        self.outcomes, self.calls = list(outcomes), 0

    def complete(self, model, system, message, schema):
        self.calls += 1
        step = self.outcomes.pop(0) if len(self.outcomes) > 1 else self.outcomes[0]
        if isinstance(step, Exception):
            raise step
        return {"verdict": {"answer": model}, "error": None, "input_tokens": 1, "output_tokens": 1}


ROWS = [{"doc_id": "DOC-01", "page": 1, "text": "Part 1 approved on March 3, 2024.", "read_by": "ocr"},
        {"doc_id": "DOC-01", "page": 2, "text": "Building A only.", "read_by": "text"},
        {"doc_id": "DOC-02", "page": 1, "text": "QRE of $24,600,000.", "read_by": "text"}]


def _local_room(folder, room="T9"):
    store._write(folder / room / "chunks.json", ROWS)
    (folder / room / "documents").mkdir(parents=True)
    for doc in ("DOC-01_Part1.pdf", "DOC-02_Budget.pdf"):
        (folder / room / "documents" / doc).write_bytes(b"%PDF-1.4 " + doc.encode())
    return folder / room


def _pdf(pages=1):
    from pypdf import PdfWriter
    import io
    w = PdfWriter()
    for _ in range(pages):
        w.add_blank_page(width=200, height=200)
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()
