"""Brief section 6: results must not depend on test answers or cases hard-coded into the product.

Fails when text from evals/cases.jsonl (case inputs, quotes cited as the label source, case ids,
canary strings) appears in any file under prawdowid/ (prompts, rules, data, fixtures).
Inputs and quotes are compared as word 8-grams, so short common phrases do not trigger.
"""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CASES = ROOT / "evals" / "cases.jsonl"
PRODUCT = ROOT / "prawdowid"
N = 8
TRANSLATE = str.maketrans(
    {"„": '"', "”": '"', "“": '"', "’": "'", "‘": "'", "«": '"', "»": '"'}
)
QUOTED = re.compile(r"'([^']{20,}?)'")


def words(text: str) -> list[str]:
    folded = text.translate(TRANSLATE).casefold()
    return re.sub(r"[\"'`]+", " ", folded).split()


def ngrams(text: str, n: int = N) -> set[str]:
    w = words(text)
    return {" ".join(w[i : i + n]) for i in range(len(w) - n + 1)}


def load_cases(path: Path = CASES) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text("utf-8").splitlines()
        if line.strip()
    ]


def case_texts(case: dict) -> list[tuple[str, str]]:
    """(kind, text) pairs that must not appear in product files: input and quoted label sources."""
    texts = [("input", case["input"].get("text") or "")]
    texts += [("expected quote", q) for q in QUOTED.findall(case.get("source", ""))]
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
        grams = ngrams(text)
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
    leaks = find_leaks(load_cases())
    assert not leaks, "eval data leaked into the product:\n" + "\n".join(leaks)


def test_cases_file_is_not_trivially_empty():
    cases = load_cases()
    assert len(cases) >= 30 and product_files()


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
