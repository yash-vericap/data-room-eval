"""The app, once through, with a stand-in for the model; and several runs of one data room."""
import json as _json

from eval import judge, stats
from eval import reality_check as rc

from helpers import NEW_ISSUE, ROOT, _REAL, CheckClient


def test_app_runs_end_to_end(repo, monkeypatch):
    from streamlit.testing.v1 import AppTest
    monkeypatch.setattr(judge, "_client", lambda: CheckClient(leftover=_REAL))
    payload = _json.loads((ROOT / "submissions" / "baseline" / "CHATGPT-HTC02-R1.json").read_text(encoding="utf-8"))
    payload = {"result": {"discrepancies": payload["findings"][:4] + [NEW_ISSUE]}}
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=180).run()
    assert not at.exception and at.header[0].value == "Vericap run check"

    def press(label):
        next(b for b in at.button if b.label.startswith(label)).click().run()
        assert not at.exception, at.exception

    at.selectbox(key="rc_room").set_value("HTC02").run()
    at.text_area(key="rc_text").set_value("{not json").run()
    press("Read the run")
    assert "Not valid JSON" in at.error[0].value
    at.text_area(key="rc_text").set_value(_json.dumps(payload)).run()
    press("Read the run")
    press("Run the check")
    labels = [m.label for m in at.metric]
    assert labels[:4] == ["Accuracy", "Found", "Partially found", "Missed"]
    assert [t.label.split(" (")[0] for t in at.tabs] == ["Summary", "Comparison", "Run details", "Report and audit"]
    assert any("ranks" in m.value for m in at.markdown) and any("How the ranking works" in m.value for m in at.markdown)
    assert not any("How these numbers are calculated" in m.value for m in at.markdown)  # behind a toggle
    next(t for t in at.toggle if t.label == "Explain the accuracy").set_value(True).run()
    assert any("How these numbers are calculated" in m.value for m in at.markdown)
    assert any("vc-cmp" in m.value for m in at.markdown)                               # ground truth and run side by side
    assert any(s.label == "Show" for s in at.get("button_group"))                      # Comparison: pick the groups
    assert any("Miscellaneous" in m.value for m in at.markdown)
    press("Change the verdict")                                                        # opens a pop-up
    assert any(r.label == "New verdict" for r in at.radio)
    at = at.run()
    if any(b.label == "Open" for b in at.button):                                      # a miss opens in a pop-up too
        press("Open")
        assert any("vc-cmp" in m.value for m in at.markdown)
    assert at.sidebar.radio[0].options == ["Vericap run check", "Data rooms", "Upload evaluation sheet", "Stats"]
    assert not at.sidebar.selectbox and not at.sidebar.checkbox                       # the sidebar only moves between screens

    # a second, different JSON file for the same data room is a second run, kept apart from the first
    payload["result"]["discrepancies"] = payload["result"]["discrepancies"][1:]
    at.text_area(key="rc_text").set_value(_json.dumps(payload)).run()
    press("Read the run")
    press("Run the check")
    runs = rc.list_checks("HTC02")
    assert len(runs) == 2 and len({r["label"] for r in runs}) == 2                     # two runs, two different names
    for screen in ("Data rooms", "Upload evaluation sheet", "Stats"):
        at.sidebar.radio[0].set_value(screen).run()
        assert not at.exception, (screen, at.exception)
    assert any(m.label == "Runs checked" and m.value == "2" for m in at.metric)
    at.selectbox(key="w_room_filter").set_value("HTC02").run()                         # one data room: compare its runs
    assert not at.exception, at.exception
    assert any(m.label == "Found every time" for m in at.metric) and any(m.label == "Gained" for m in at.metric)
    assert (ROOT / "answer_key" / "library_v1.json").read_bytes() == (repo / "answer_key" / "library_v1.json").read_bytes()


def test_runs_of_one_data_room_are_compared_case_by_case(empty):
    a = ({"label": "A"}, {"cases": [{"case_id": "T1-001", "status": rc.FOUND, "severity": "Critical", "set": "Withheld",
                                     "summary": "s", "weight": 8},
                                    {"case_id": "T1-003", "status": rc.MISSED, "severity": "High", "set": "Withheld",
                                     "summary": "s", "weight": 4}]})
    b = ({"label": "B"}, {"cases": [{**a[1]["cases"][0], "status": rc.PARTIAL}, {**a[1]["cases"][1], "status": rc.FOUND}]})
    rows = {r["Case"]: r for r in stats.stability([a, b])}
    assert rows["T1-001"]["Pattern"] == "Found sometimes" and rows["T1-001"]["Found in"] == "1 of 2"
    change = {r["Case"]: r["Change"] for r in stats.compare(a, b)}
    assert change == {"T1-001": "Worse", "T1-003": "Gained"}
