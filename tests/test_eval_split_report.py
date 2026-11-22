from evals import run, split_report

ERR = "status:technical_error"


def row(case_id, expected, predicted, seconds=1.0, errors=()):
    return {
        "id": case_id,
        "scenario": case_id[-3],
        "expected": expected,
        "expected_label": expected,
        "predicted": [predicted],
        "seconds": [seconds],
        "errors": list(errors),
        "correct": not errors and predicted == expected,
    }


REPORT = {
    "commit": "abcdef1234",
    "mode": "full",
    "cases": [
        row("A01", "potwierdzone", "potwierdzone", 2.0),
        row("A02", "fałszywe", "potwierdzone", 4.0),
        row("FC-A01", "fałszywe", "fałszywe", 10.0),
        row(
            "FC-A02",
            "brak wystarczających dowodów",
            "brak wystarczających dowodów",
            20.0,
        ),
        row("FC-A03", "potwierdzone", ERR, 90.0, errors=["TimeoutError"]),
    ],
}


def test_split_groups_by_fc_prefix():
    groups = split_report.split(REPORT["cases"])
    assert [r["id"] for r in groups["FC-*"]] == ["FC-A01", "FC-A02", "FC-A03"]
    assert [r["id"] for r in groups["rest"]] == ["A01", "A02"]


def test_errored_rows_count_as_wrong_and_slow():
    fc = split_report.group_metrics(split_report.split(REPORT["cases"])["FC-*"])
    assert (fc["cases"], fc["errored"]) == (3, 1)
    assert round(fc["accuracy"], 3) == 0.667
    assert fc["abstention"] == 1.0
    assert fc["median_latency_s"] == 20.0
    assert fc["macro_f1"] < 1.0
    rest = split_report.group_metrics(split_report.split(REPORT["cases"])["rest"])
    assert rest["accuracy"] == 0.5 and rest["abstention"] is None


def test_matches_run_summarize_and_macro_f1_with_errors():
    rows = [
        row("FC-A01", "fałszywe", "fałszywe", 10.0),
        row("FC-A03", "potwierdzone", ERR, 90.0, errors=["TimeoutError"]),
    ]
    fc = split_report.group_metrics(rows)
    assert fc["macro_f1"] == 0.5
    assert fc["accuracy"] == 0.5
    official = run.summarize(rows)["by_case_set"]["FC"]
    assert fc["accuracy"] == official["correct"] / official["cases"]


def test_old_format_rows_without_expected_label():
    old = {
        "id": "J01",
        "expected": "technical_error",
        "predicted": [ERR],
        "seconds": [1.0],
        "errors": [],
    }
    assert split_report.group_metrics([old])["accuracy"] == 1.0


def test_format_report_prints_both_rows():
    out = split_report.format_report(REPORT)
    assert "FC-*" in out and "rest" in out and "abcdef1" in out
