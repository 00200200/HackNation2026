import json
import re
import sys
import time
import urllib.error

import pytest

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
        adapter,
        "ask",
        lambda payload, channel, **_: asked.append(payload) or {"claims": []},
    )
    monkeypatch.setattr(run, "git", lambda *args: "")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["run", "--cases", str(cases)])

    run.main()

    report = json.loads((tmp_path / "evals/results/latest.json").read_text())
    assert asked == [{"text": "x"}]
    assert report["skipped"] == [{"id": "J1", "scenario": "J", "reason": "no fault"}]
    assert "J" not in report["scenarios"] and report["coverage_ok"] is False


CASES = [
    {"id": f"C{i}", "scenario": "AB"[i % 2], "input": {"text": f"t{i}"}}
    | {"expected_verdict": "fałszywe" if i % 3 else "potwierdzone"}
    for i in range(8)
]


def fake_answer(payload, channel):
    """Deterministic per input, with a jitter so concurrent cases finish out of order."""
    i = int(payload["text"][1:])
    time.sleep(0.01 * (len(CASES) - i))
    verdict = "fałszywe" if i % 2 else "potwierdzone"
    return {"claims": [{"text": "c", "verdict": verdict, "evidence": []}]}


def run_eval(tmp_path, monkeypatch, *flags, cases=CASES, ask=fake_answer):
    path = tmp_path / "cases.jsonl"
    path.write_text("".join(json.dumps(c) + "\n" for c in cases), encoding="utf-8")
    asked = []
    monkeypatch.setattr(adapter, "wait_turn", lambda: None)
    monkeypatch.setattr(
        adapter, "ask", lambda p, ch, **_: asked.append(p["text"]) or ask(p, ch)
    )
    monkeypatch.setattr(run, "git", lambda *args: "")
    monkeypatch.setattr(run, "RETRY_BACKOFF_S", 0)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["run", "--cases", str(path), *flags])
    run.main()
    report = json.loads((tmp_path / "evals/results/latest.json").read_text())
    return report, asked


def partials(tmp_path):
    return sorted((tmp_path / "evals/results").glob("run-*.partial.jsonl"))


def test_concurrent_run_scores_like_sequential(tmp_path, monkeypatch, capsys):
    seq, _ = run_eval(tmp_path, monkeypatch, "--concurrency", "1")
    par, _ = run_eval(tmp_path, monkeypatch, "--concurrency", "4")

    def without_latency(report):
        return {k: v for k, v in report["metrics"].items() if k != "median_latency_s"}

    assert without_latency(par) == without_latency(seq)
    assert [c["id"] for c in par["cases"]] == [c["id"] for c in CASES]
    assert [c["predicted"] for c in par["cases"]] == [
        c["predicted"] for c in seq["cases"]
    ]
    lines = [line for line in capsys.readouterr().out.splitlines() if "ETA" in line]
    assert len(lines) == 2 * len(CASES)
    assert re.match(
        r"\[1/8\] C\d+ (ok|FAIL) verdict=\S+ expected=\S+ [\d.]+s", lines[0]
    )
    assert "C1 ok verdict=fałszywe expected=fałszywe" in "\n".join(lines)
    assert "C2 FAIL verdict=potwierdzone expected=fałszywe" in "\n".join(lines)
    finished = run.load_jsonl(str(partials(tmp_path)[-1]))
    assert sorted(r["case"]["id"] for r in finished) == sorted(c["id"] for c in CASES)


def test_resume_skips_finished_cases(tmp_path, monkeypatch):
    first, _ = run_eval(tmp_path, monkeypatch)
    partial = partials(tmp_path)[0]
    rows = run.load_jsonl(str(partial))
    kept = [r for r in rows if r["case"]["id"] not in ("C3", "C5")]
    partial.write_text("".join(json.dumps(r) + "\n" for r in kept), encoding="utf-8")

    report, asked = run_eval(tmp_path, monkeypatch, "--resume", str(partial))

    assert sorted(asked) == ["t3", "t5"]
    assert report["metrics"]["macro_f1"] == first["metrics"]["macro_f1"]
    assert len(report["reused_cases"]) == 6


def test_retry_failed_and_only_rerun_some_cases(tmp_path, monkeypatch):
    def flaky(payload, channel):
        if payload["text"] == "t2":
            raise ValueError("bad JSON")
        return fake_answer(payload, channel)

    first, _ = run_eval(tmp_path, monkeypatch, ask=flaky)
    assert first["cases"][2]["errors"] == ["ValueError: bad JSON"]

    report, asked = run_eval(
        tmp_path, monkeypatch, "--retry-failed", str(partials(tmp_path)[0])
    )
    assert asked == ["t2"] and report["cases"][2]["errors"] == []
    assert report["n_cases"] == len(CASES)

    report, asked = run_eval(tmp_path, monkeypatch, "--only", "C1,C4")
    assert sorted(asked) == ["t1", "t4"] and report["n_cases"] == 2


def test_rate_limit_is_retried_once(tmp_path, monkeypatch, capsys):
    attempts = []

    def limited(payload, channel):
        attempts.append(payload["text"])
        if payload["text"] == "t0" and attempts.count("t0") == 1:
            raise urllib.error.HTTPError("u", 429, "Too Many Requests", {}, None)
        if payload["text"] == "t1":
            raise urllib.error.HTTPError("u", 503, "Unavailable", {}, None)
        return fake_answer(payload, channel)

    report, _ = run_eval(tmp_path, monkeypatch, ask=limited, cases=CASES[:3])

    assert attempts.count("t0") == 2 and report["cases"][0]["errors"] == []
    assert attempts.count("t1") == 2 and report["cases"][1]["errors"]
    assert attempts.count("t2") == 1
    out = capsys.readouterr().out
    assert "retry C0 web after HTTPError: HTTP Error 429" in out


def test_crash_stops_starting_new_cases(tmp_path, monkeypatch):
    started = []

    def crash(payload, channel):
        started.append(payload["text"])
        if payload["text"] == "t0":
            raise KeyError("boom")
        time.sleep(0.05)
        return fake_answer(payload, channel)

    with pytest.raises(KeyError):
        run_eval(tmp_path, monkeypatch, "--concurrency", "2", ask=crash)
    assert len(started) < len(CASES)


def test_run_writes_one_history_entry(tmp_path, monkeypatch):
    report, _ = run_eval(tmp_path, monkeypatch, "--note", "smoke")

    history_files = sorted((tmp_path / "evals/results/history").glob("*.json"))
    assert len(history_files) == 1
    assert json.loads(history_files[0].read_text()) == report

    lines = (tmp_path / "evals/results/HISTORY.md").read_text().splitlines()
    assert lines[0].startswith("| timestamp |")
    assert len(lines) == 3  # header + separator + one row
    assert (
        "nocommit" in lines[2]
    )  # commit is "" in tests -> sha falls back to "nocommit"
    assert "smoke" in lines[2]

    summary = report["summary"]
    assert summary["by_case_set"]["A-J"]["cases"] == len(CASES)
    assert summary["by_case_set"]["FC"]["cases"] == 0


def test_summary_counts_status_expected_cases_correctly(tmp_path, monkeypatch):
    cases = [
        {
            "id": "J1",
            "scenario": "J",
            "input": {"text": "t0"},
            "expected_status": "technical_error",
        }
    ]

    def ask(payload, channel):
        return {"status": "technical_error"}

    report, _ = run_eval(tmp_path, monkeypatch, cases=cases, ask=ask)
    assert report["summary"]["by_scenario"]["J"] == {"cases": 1, "correct": 1}


def test_two_runs_append_two_history_lines(tmp_path, monkeypatch):
    run_eval(tmp_path, monkeypatch)
    run_eval(tmp_path, monkeypatch)

    history_files = sorted((tmp_path / "evals/results/history").glob("*.json"))
    assert len(history_files) == 2
    lines = (tmp_path / "evals/results/HISTORY.md").read_text().splitlines()
    assert len(lines) == 4  # header + separator + two rows


def test_summary_splits_fc_and_az_case_sets(tmp_path, monkeypatch):
    cases = CASES + [
        {"id": "FC-1", "scenario": "A", "input": {"text": "t100"}}
        | {"expected_verdict": "potwierdzone"}
    ]

    def ask(payload, channel):
        if payload["text"] == "t100":
            return {
                "claims": [{"text": "c", "verdict": "potwierdzone", "evidence": []}]
            }
        return fake_answer(payload, channel)

    report, _ = run_eval(tmp_path, monkeypatch, cases=cases, ask=ask)
    assert report["summary"]["by_case_set"]["FC"] == {"cases": 1, "correct": 1}
    assert report["summary"]["by_case_set"]["A-J"]["cases"] == len(CASES)


def test_dirty_rows_are_reused_only_by_a_dirty_run(tmp_path):
    case = CASES[0]
    row = {"case": case, "runs": [], "repeat": None, "commit": "abc", "dirty": True}
    path = tmp_path / "p.jsonl"
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    clean, dirty = {"commit": "abc", "dirty": False}, {"commit": "abc", "dirty": True}
    assert run.load_reusable(str(path), [case], clean) == {}
    assert run.load_reusable(str(path), [case], dirty) == {case["id"]: row}
    assert run.load_reusable(str(path), [case], {"commit": "x", "dirty": True}) == {}


def test_simulate_is_sent_as_the_fault(monkeypatch):
    seen = []
    monkeypatch.setattr(adapter, "wait_turn", lambda: None)
    monkeypatch.setattr(
        adapter,
        "ask",
        lambda p, ch, fault=None: seen.append(fault) or {"status": "technical_error"},
    )
    run.call({"id": "J1", "input": {"text": "t"}, "simulate": "llm_unavailable"}, "web")
    run.call({"id": "A1", "input": {"text": "t"}}, "web")
    assert seen == ["llm_unavailable", None]


def test_status_only_ok_case_counts_any_verdict(tmp_path, monkeypatch):
    cases = [{"id": "J1", "scenario": "J", "input": {"text": "t0"}}]
    cases.append(cases[0] | {"id": "J2", "input": {"text": "t1"}})

    def ask(payload, channel):
        if payload["text"] == "t1":
            return {"status": "technical_error"}
        return {"claims": [{"text": "c", "verdict": "nie sprawdzono", "evidence": []}]}

    report, _ = run_eval(tmp_path, monkeypatch, cases=cases, ask=ask)
    assert report["summary"]["by_scenario"]["J"] == {"cases": 2, "correct": 1}
