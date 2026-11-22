"""Brief section 6: results must not depend on test answers or cases hard-coded into the product.

Fails when text from evals/cases.jsonl (case inputs, quotes cited as the label source, case ids,
canary strings) appears in any file under prawdowid/ or frontend/ (prompts, rules, data, fixtures, UI).
Texts are compared as word 8-grams over letters and digits (case and punctuation folded); an input
shorter than 8 words but with at least 4 is compared whole. Only the example chips of the web UI
(`data-example="..."`) are exempt: they deliberately use the organiser's questions (WORKLOG, #16).
"""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CASES = ROOT / "evals" / "cases.jsonl"
PRODUCT = ROOT / "prawdowid"
FRONTEND = ROOT / "frontend"
N = 8
MIN_WORDS = 4
MIN_QUOTE = 20
QUOTED = (re.compile(r"'([^']*)'"), re.compile(r"„([^”]*)”"))
EXEMPT = re.compile(r'data-example="[^"]*"')


def words(text: str) -> list[str]:
    return re.findall(r"\w+", text.casefold())


def ngrams(text: str, n: int = N) -> set[str]:
    w = words(text)
    if MIN_WORDS <= len(w) < n:
        n = len(w)
    return {" ".join(w[i : i + n]) for i in range(len(w) - n + 1)}


def file_grams(text: str, n: int) -> set[str]:
    """n-grams of a product file for any n up to N, so short inputs match as whole phrases."""
    w = words(EXEMPT.sub("", text))
    return {
        " ".join(w[i : i + k])
        for k in range(MIN_WORDS, n + 1)
        for i in range(len(w) - k + 1)
    }


def load_cases(path: Path = CASES) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text("utf-8").splitlines()
        if line.strip()
    ]


def case_texts(case: dict) -> list[tuple[str, str]]:
    """(kind, text) pairs that must not appear in product files: input and quoted label sources."""
    texts = [("input", case["input"].get("text") or "")]
    source = case.get("source", "")
    texts += [
        ("expected quote", q)
        for pattern in QUOTED
        for q in pattern.findall(source)
        if len(q) >= MIN_QUOTE
    ]
    return texts


def product_files(root: Path = PRODUCT) -> list[Path]:
    return [
        p
        for p in sorted(root.rglob("*"))
        if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"
    ]


def find_leaks(cases: list[dict], root: Path = PRODUCT) -> list[str]:
    leaks = []
    for path in product_files(root):
        try:
            text = path.read_text("utf-8")
        except UnicodeDecodeError:
            continue
        grams = file_grams(text, N)
        rel = path.relative_to(root.parent)
        for case in cases:
            for kind, case_text in case_texts(case):
                for gram in sorted(ngrams(case_text) & grams):
                    leaks.append(f"{rel}: {case['id']} {kind} 8-gram: {gram!r}")
            needles = [case["id"]] + ([case["canary"]] if case.get("canary") else [])
            for needle in needles:
                if re.search(rf"(?<![\w-]){re.escape(needle)}(?![\w-])", text):
                    leaks.append(f"{rel}: case id or canary {needle!r}")
    return leaks


def test_product_does_not_contain_eval_cases():
    cases = load_cases()
    leaks = find_leaks(cases) + find_leaks(cases, FRONTEND)
    assert not leaks, "eval data leaked into the product:\n" + "\n".join(leaks)


def test_cases_file_is_not_trivially_empty():
    cases = load_cases()
    assert len(cases) >= 30 and product_files() and product_files(FRONTEND)


def test_detects_planted_leaks(tmp_path):
    cases = [
        {
            "id": "Z99",
            "input": {
                "text": "Czy „Polska” jest  członkiem NATO od 1999 roku, tak naprawdę?"
            },
            "canary": "KANAREK-7",
            "source": "X, 'Poland became a NATO member on 12 March 1999.'",
        }
    ]
    (tmp_path / "prompt.txt").write_text(
        "Example: czy polska jest członkiem nato od 1999 roku, tak naprawdę", "utf-8"
    )
    (tmp_path / "rules.md").write_text(
        "poland became a nato member on 12 march 1999", "utf-8"
    )
    (tmp_path / "ids.txt").write_text("see case Z99 and KANAREK-7", "utf-8")
    (tmp_path / "clean.txt").write_text("czy polska jest członkiem nato", "utf-8")
    leaks = "\n".join(find_leaks(cases, tmp_path))
    assert "prompt.txt: Z99 input" in leaks
    assert "rules.md: Z99 expected quote" in leaks
    assert "ids.txt: case id or canary 'Z99'" in leaks
    assert "KANAREK-7" in leaks
    assert "clean.txt" not in leaks


def test_a01_real_source_quote_is_detected(tmp_path):
    a01 = load_cases()[0]
    assert a01["id"] == "A01"
    (tmp_path / "judge.py").write_text(
        'EXAMPLE = "Poland became a NATO member on 12 March 1999."', "utf-8"
    )
    assert "A01 expected quote" in "\n".join(find_leaks([a01], tmp_path))


def test_short_inputs_punctuation_and_escapes(tmp_path):
    cases = [
        {"id": "S1", "input": {"text": "Czy niemieckie radiowozy jadą do Warszawy?"}},
        {"id": "S2", "input": {"text": "Czy Polska jest członkiem NATO od 1999 roku?"}},
    ]
    (tmp_path / "p.py").write_text(
        'A = "Czy niemieckie radiowozy jadą do Warszawy"\nB = "Czy Polska jest członkiem NATO od 1999 roku\\n"',
        "utf-8",
    )
    leaks = "\n".join(find_leaks(cases, tmp_path))
    assert "S1 input" in leaks and "S2 input" in leaks


def test_example_chips_are_exempt_but_other_ui_text_is_not(tmp_path):
    case = [
        {"id": "S3", "input": {"text": "Czy Polska jest członkiem NATO od 1999 roku?"}}
    ]
    (tmp_path / "a.html").write_text(
        '<button data-example="Czy Polska jest członkiem NATO od 1999 roku?">x</button>',
        "utf-8",
    )
    assert find_leaks(case, tmp_path) == []
    (tmp_path / "b.html").write_text(
        "<p>Czy Polska jest członkiem NATO od 1999 roku?</p>", "utf-8"
    )
    assert "b.html" in "\n".join(find_leaks(case, tmp_path))
