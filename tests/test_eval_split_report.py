from evals import split_report


def row(case_id, expected, predicted, seconds=1.0, errors=()):
    return {
        "id": case_id,
        "expected": expected,
        "predicted": [predicted],
        "seconds": [seconds],
        "errors": list(errors),
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
        row("FC-A03", "potwierdzone", "", errors=["timeout"]),
    ],
}


def test_split_groups_by_fc_prefix():
    groups = split_report.split(REPORT["cases"])
    assert [r["id"] for r in groups["FC-* (held out)"]] == [
        "FC-A01",
        "FC-A02",
        "FC-A03",
    ]
    assert [r["id"] for r in groups["rest"]] == ["A01", "A02"]


def test_group_metrics_reuse_metric_functions():
    groups = split_report.split(REPORT["cases"])
    fc = split_report.group_metrics(groups["FC-* (held out)"])
    assert (fc["cases"], fc["errored"]) == (3, 1)
    assert fc["accuracy"] == 1.0 and fc["macro_f1"] == 1.0 and fc["abstention"] == 1.0
    assert fc["median_latency_s"] == 15.0
    rest = split_report.group_metrics(groups["rest"])
    assert rest["accuracy"] == 0.5 and rest["abstention"] is None


def test_format_report_prints_both_rows():
    out = split_report.format_report(REPORT)
    assert "FC-* (held out)" in out and "rest" in out and "abcdef1" in out
