import json
import sys

from evals import adapter, run


def test_skipped_case_is_reported_not_run(tmp_path, monkeypatch):
    cases = tmp_path / "cases.jsonl"
    cases.write_text(
        json.dumps({"id": "A1", "scenario": "A", "input": {"text": "x"}})
        + "\n"
        + json.dumps(
            {"id": "J1", "scenario": "J", "input": {"text": "y"}, "skip": "no fault"}
        )
        + "\n",
        encoding="utf-8",
    )
    asked = []
    monkeypatch.setattr(adapter, "wait_turn", lambda: None)
    monkeypatch.setattr(
        adapter, "ask", lambda payload, channel: asked.append(payload) or {"claims": []}
    )
    monkeypatch.setattr(run, "git", lambda *args: "")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["run", "--cases", str(cases)])

    run.main()

    report = json.loads((tmp_path / "evals/results/latest.json").read_text())
    assert asked == [{"text": "x"}]
    assert report["skipped"] == [{"id": "J1", "scenario": "J", "reason": "no fault"}]
    assert "J" not in report["scenarios"] and report["coverage_ok"] is False
