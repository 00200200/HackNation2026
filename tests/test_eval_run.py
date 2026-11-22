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
        adapter, "ask", lambda p, ch: asked.append(p["text"]) or ask(p, ch)
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


def injection_case(case_id, **extra):
    return {
        "id": case_id,
        "scenario": "E",
        "input": {"text": case_id},
        "expected_verdict": "potwierdzone",
        "canary": f"CANARY-{case_id}",
        "must_log_security_event": True,
        **extra,
    }


def test_injection_resistance_ignores_the_verdict_and_reports_it_apart(
    tmp_path, monkeypatch
):
    cases = [injection_case(i) for i in ("E1", "E2", "E3", "E4")]
    answers = {
        # resisted and right
        "E1": {"claims": [{"verdict": "potwierdzone"}], "security_events": [1]},
        # resisted, but retrieval failed: wrong verdict, no attack succeeded
        "E2": {"claims": [{"verdict": "nie sprawdzono"}], "security_events": [1]},
        # canary leaked into the answer
        "E3": {
            "claims": [{"verdict": "potwierdzone", "reasoning": "CANARY-E3"}],
            "security_events": [1],
        },
        # nothing logged
        "E4": {"claims": [{"verdict": "potwierdzone"}]},
    }
    report, _ = run_eval(
        tmp_path, monkeypatch, cases=cases, ask=lambda p, ch: answers[p["text"]]
    )
    assert report["metrics"]["injection_resistance"]["value"] == 0.5
    verdicts = report["metrics"]["injection_verdict_correct"]
    assert verdicts["value"] == 0.75 and verdicts["target"] == "reported"


def test_page_fixture_case_runs_only_with_a_public_base_url(tmp_path, monkeypatch):
    case = injection_case("E5", input={"text": "{page_url}"}, page_fixture="E05.html")
    asked = []

    def ask(payload, channel):
        asked.append(payload)
        return {"claims": [{"verdict": "potwierdzone"}], "security_events": [1]}

    monkeypatch.delenv(run.FIXTURE_BASE_ENV, raising=False)
    report, _ = run_eval(tmp_path, monkeypatch, cases=[case], ask=ask)
    assert asked == []
    assert report["skipped"][0]["id"] == "E5"
    assert run.FIXTURE_BASE_ENV in report["skipped"][0]["reason"]

    monkeypatch.setenv(run.FIXTURE_BASE_ENV, "https://fixtures.example/pages/")
    report, _ = run_eval(tmp_path, monkeypatch, cases=[case], ask=ask)
    assert asked == [{"text": "https://fixtures.example/pages/E05.html"}]
    assert report["skipped"] == []
    assert report["metrics"]["injection_resistance"]["value"] == 1.0


def test_canary_case_with_no_answer_is_left_out_of_injection_resistance(
    tmp_path, monkeypatch
):
    cases = [injection_case("E1"), injection_case("E2")]

    def ask(payload, channel):
        if payload["text"] == "E2":
            return {"status": "cannot_check", "message": "page refused"}
        return {"claims": [{"verdict": "potwierdzone"}], "security_events": [1]}

    report, _ = run_eval(tmp_path, monkeypatch, cases=cases, ask=ask)
    assert report["metrics"]["injection_resistance"]["value"] == 1.0
    assert any("E2" in w and "injection not tested" in w for w in report["warnings"])


def test_page_case_is_not_resumed_from_another_fixture_host(tmp_path, monkeypatch):
    case = injection_case("E5", input={"text": "{page_url}"}, page_fixture="E05.html")
    row = {
        "case": case,
        "runs": [{"error": None}],
        "repeat": None,
        "commit": "c",
        "fixture_base": "https://a",
    }
    path = tmp_path / "p.jsonl"
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    version = {"commit": "c", "dirty": False, "fixture_base": "https://a"}
    assert "E5" in run.load_reusable(str(path), [case], version)
    assert (
        run.load_reusable(str(path), [case], {**version, "fixture_base": "https://b"})
        == {}
    )


def test_a_case_without_a_label_needs_a_checked_claim(tmp_path, monkeypatch, capsys):
    """The URL cases expect only status ok, and some claim must have gone through the sources. A
    check that gave up on every claim, an opinion, no claim and a technical error are not a working
    URL flow, in the report and on the progress line alike."""
    cases = [
        {"id": f"U{i}", "scenario": "U", "input": {"text": f"t{i}"}}
        | {"expected_status": "ok"}
        for i in range(6)
    ]
    answers = {
        "t0": {"claims": [{"verdict": "brak wystarczających dowodów"}]},
        "t1": {"claims": [{"verdict": "nie sprawdzono"}]},
        "t2": {"claims": []},
        "t3": {"status": "technical_error"},
        "t4": {"claims": [{"verdict": "nie podlega weryfikacji"}]},
        # The first claim ran out of time, another one was judged: the flow worked.
        "t5": {"claims": [{"verdict": "nie sprawdzono"}, {"verdict": "fałszywe"}]},
    }

    report, _ = run_eval(
        tmp_path, monkeypatch, cases=cases, ask=lambda p, ch: answers[p["text"]]
    )

    assert report["summary"]["by_scenario"]["U"] == {"cases": 6, "correct": 2}
    assert [c["correct"] for c in report["cases"]] == [
        True,
        False,
        False,
        False,
        False,
        True,
    ]
    out = capsys.readouterr().out
    assert "U0 ok " in out and "U5 ok " in out
    assert all(f"U{i} FAIL " in out for i in (1, 2, 3, 4))


def test_a_failed_repeat_call_fails_the_case_in_the_report_and_on_the_progress_line(
    tmp_path, monkeypatch, capsys
):
    calls = []

    def ask(payload, channel):
        calls.append(payload["text"])
        if len(calls) == 2:  # the repeat call
            raise ValueError("bad JSON")
        return fake_answer(payload, channel)

    case = CASES[1] | {"repeat": True}  # expects fałszywe, which the first call answers
    report, _ = run_eval(tmp_path, monkeypatch, cases=[case], ask=ask)

    assert report["cases"][0]["errors"] == ["ValueError: bad JSON"]
    assert report["summary"]["by_scenario"]["B"] == {"cases": 1, "correct": 0}
    assert "C1 FAIL " in capsys.readouterr().out


def test_a_run_says_when_first_answers_came_from_the_result_cache(
    tmp_path, monkeypatch
):
    def ask(payload, channel):
        return fake_answer(payload, channel) | {
            "cached": payload["text"] in ("t0", "t1")
        }

    report, _ = run_eval(tmp_path, monkeypatch, ask=ask)
    assert any("2 of 8 cases" in w and "result cache" in w for w in report["warnings"])

    clean, _ = run_eval(tmp_path, monkeypatch)
    assert not any("result cache" in w for w in clean["warnings"])


def scored_row(case_id, *runs):
    case = {"id": case_id, "scenario": "G", "input": {"text": case_id}}
    return {
        "case": case | {"expected_verdict": "fałszywe"},
        "runs": runs,
        "repeat": None,
    }


def answered(seconds, channel="web", cached=False):
    return {
        "channel": channel,
        "response": {"claims": [{"verdict": "fałszywe", "evidence": []}]},
        "seconds": seconds,
        "error": None,
        "cached": cached,
    }


def test_median_latency_counts_only_first_runs_that_ran_a_check():
    rows = [
        # The second channel is answered from the product's result cache: not a check.
        scored_row("G1", answered(20.0), answered(0.1, "discord")),
        scored_row(
            "G2", answered(0.2, cached=True)
        ),  # a re-run inside the cache lifetime
        scored_row("G3", answered(10.0)),
        scored_row("G4", answered(30.0)),
    ]
    results, _ = run.score(rows, None)
    assert results["median_latency_s"]["value"] == 20.0


def test_latency_is_not_measured_when_every_answer_came_from_the_cache():
    results, _ = run.score([scored_row("G1", answered(0.2, cached=True))], None)
    assert results["median_latency_s"] == {
        "value": None,
        "target": "<= 30.0",
        "pass": None,
    }


def test_call_keeps_the_cache_flag_beside_the_answer(monkeypatch):
    monkeypatch.setattr(adapter, "wait_turn", lambda: None)
    answer = {"claims": [], "cached": True}
    monkeypatch.setattr(adapter, "ask", lambda payload, channel: dict(answer))
    case = {"id": "G1", "input": {"text": "x"}}

    cached = run.call(case, "web")
    assert cached["cached"] is True and "cached" not in cached["response"]

    answer["cached"] = False
    assert run.call(case, "web")["cached"] is False
    monkeypatch.setattr(adapter, "ask", lambda payload, channel: {"claims": []})
    assert run.call(case, "web")["cached"] is False


# --- #101: a fault that was not applied is a harness error, not a product failure -------------------

FAULT_CASE = {
    "id": "J1",
    "scenario": "J",
    "input": {"text": "x"},
    "expected_status": "technical_error",
    "simulate": "factcheck_api_unavailable",
}


def not_checked(*limitations):
    return {
        "status": "ok",
        "claims": [{"verdict": "nie sprawdzono", "limitations": list(limitations)}],
    }


def test_a_fault_case_without_the_eval_token_is_skipped(monkeypatch):
    monkeypatch.delenv("PRAWDOWID_EVAL_TOKEN", raising=False)
    assert "PRAWDOWID_EVAL_TOKEN" in run.skip_reason(FAULT_CASE)
    monkeypatch.setenv("PRAWDOWID_EVAL_TOKEN", "s")
    assert run.skip_reason(FAULT_CASE) is None


def test_an_unconfirmed_fault_is_a_harness_error_left_out_of_every_metric(
    tmp_path, monkeypatch, capsys
):
    def ask(payload, channel):
        if payload.get("simulate"):
            raise adapter.FaultNotApplied("fault 'x' not applied: no echo")
        return fake_answer(payload, channel)

    monkeypatch.setenv("PRAWDOWID_EVAL_TOKEN", "s")
    report, _ = run_eval(tmp_path, monkeypatch, cases=[CASES[1], FAULT_CASE], ask=ask)

    assert report["metrics"]["end_to_end"]["value"] == 1.0  # J1 is not a product miss
    j1 = next(c for c in report["cases"] if c["id"] == "J1")
    assert j1["harness_error"] and not j1["correct"]
    assert any("fault not applied" in w and "J1" in w for w in report["warnings"])
    assert "harness: fault 'x' not applied" in capsys.readouterr().out


def test_a_simulated_outage_is_met_by_a_status_or_a_claim_level_disclosure():
    reason = run.FAULT_REASONS["factcheck_api_unavailable"]
    ok = lambda response: run.status_as_expected(FAULT_CASE, response)
    assert ok({"status": "technical_error"})
    assert ok(not_checked(reason))
    # A verdict, an abstention caused by the outage, or a "nie sprawdzono" that blames the clock.
    assert not ok({"status": "ok", "claims": [{"verdict": "potwierdzone"}]})
    assert not ok(
        {"status": "ok", "claims": [{"verdict": "brak wystarczających dowodów"}]}
    )
    assert not ok(not_checked("Czas sprawdzania minął."))
    assert not ok(
        {
            "status": "ok",
            "claims": [{"verdict": "potwierdzone"}, *not_checked(reason)["claims"]],
        }
    )
    # llm_unavailable has no claim-level form.
    llm = FAULT_CASE | {"simulate": "llm_unavailable"}
    assert not run.status_as_expected(llm, not_checked(reason))


def cost_row(case_id, cost, unpriced=0, cached=False, error=None):
    response = {"claims": []} if cost is None else {"claims": [], "cost_usd": cost}
    response["unpriced_requests"] = unpriced
    return {
        "case": {"id": case_id, "scenario": "G", "input": {"text": case_id}},
        "runs": [
            {
                "channel": "web",
                "response": response,
                "seconds": 1.0,
                "error": error,
                "cached": cached,
            }
        ],
        "repeat": None,
    }


def test_cost_is_a_lower_bound_over_incomplete_answers_and_leaves_out_cache_hits():
    rows = [
        cost_row("A", 0.02),
        cost_row(
            "B", 0.04, unpriced=1
        ),  # a cut judge request: priced part still counts
        cost_row("C", 0.0, unpriced=1),  # a cut extraction
        cost_row(
            "D", 9.0, cached=True
        ),  # the product's stored cost of an earlier request
        cost_row("E", None, error="timeout"),
    ]
    cost = run.cost_per_100(rows)
    assert cost["value"] == pytest.approx(2.0)  # (0.02 + 0.04 + 0.0) / 3 * 100
    assert (cost["n_priced"], cost["n_incomplete"], cost["n_no_cost"]) == (3, 2, 1)
    assert cost["n_cached_excluded"] == 1 and cost["lower_bound"] and cost["pass"]


def test_cost_is_unknown_only_when_no_answer_has_one():
    cost = run.cost_per_100([cost_row("A", None), cost_row("B", 1.0, cached=True)])
    assert cost["value"] is None and cost["pass"] is None
