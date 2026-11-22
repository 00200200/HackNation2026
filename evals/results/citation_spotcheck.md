# Citation spot check

`citation_correctness` only shows that a quote from a corpus document is present in that document's text. It is an
upper bound and says nothing about whether the quote supports the claim. Before submitting, we check a random sample of
the citations a run actually showed, the way a juror would: open the cited page, find the quote, and read whether it
fits the verdict.

**Run:** full run on `df74cef` (the file stamps `f4c9aa8`, which is `df74cef` plus eval results),
[`history/20261122T053047.203200Z-f4c9aa8-full.json`](history/20261122T053047.203200Z-f4c9aa8-full.json). The
answers are in the run's partial file.

**Sample:** 12 of the 251 quotes shown with a URL, drawn with Python `random.Random(20261122)` and stratified by the
verdict of the claim: 3 `potwierdzone`, 4 `fałszywe`, 3 `wprowadzające w błąd`, 2 `brak wystarczających dowodów`.

**How we checked (22.11.2026):** the check was not done by a person. Three passes:

1. An agent read each page with a web fetch tool.
2. A plain HTTP fetch of the raw page was searched for the quote after normalising whitespace and quotation marks.
3. Sites that refuse scripts (Demagog and EUvsDisinfo answer 403) or render with JavaScript (PAP) were read in a
   browser, searching the page text and, for ratings, the page's ClaimReview markup.

A team member should re-open a few of these before the submission.

| # | Case | Verdict shown | Source | Quote on the page | What it says | Fits the verdict |
|---|---|---|---|---|---|---|
| 1 | U02 | brak wystarczających dowodów | [PAP](https://www.pap.pl/aktualnosci/mazowieckie-policjanci-zatrzymali-16-latke-grozaca-wysadzeniem-szkoly-w-piasecznie) | yes, it is the page title (browser) | a headline about the case | yes: a headline alone never decides a verdict |
| 2 | FC-I03 | brak wystarczających dowodów | [EUvsDisinfo](https://euvsdisinfo.eu/pl/report/polish-political-police-arrest-people-for-actions-that-are-not-a-crime/) | yes, word for word (browser) | refutes the claim | partly: EUvsDisinfo counts only as context by design, so the product abstained; the case label is `fałszywe` (a miss) |
| 3 | E02 | fałszywe | [Demagog](https://demagog.org.pl/fake_news/szczepienia-nie-powoduja-autyzmu-ta-grafika-wprowadza-w-blad/) | the rating "Fałsz" is in the page's ClaimReview markup for "Szczepienia powodują autyzm.", dated 2026-08-03 (browser) | refutes | yes |
| 4 | FC-E03 | fałszywe | [Konkret24](https://konkret24.tvn24.pl/polska/tusk-nie-przyjmujemy-wnioskow-azylowych-opozycja-nieprawda-kto-ma-racje-st9295629) | yes, word for word (raw page) | refutes: asylum was granted to 850 people | yes |
| 5 | I03 | fałszywe | [Demagog](https://demagog.org.pl/fake_news/polskie-drony-nie-zaatakowaly-rosji-falszywe-narracje-po-incydencie-na-litwie/) | yes, word for word (browser) | refutes | yes; the product shows 30.10.2026, the page says 28.10.2026 |
| 6 | FC-G01 | fałszywe | [PKW](https://samorzad2014.pkw.gov.pl/akty_prawne/0/77.html) | yes, word for word (raw page) | refutes: a ballot may have its corner cut off | yes; the source is a 2014 resolution |
| 7 | A02 | potwierdzone | [Demagog](https://demagog.org.pl/analizy_i_raporty/cala-prawda-o-unii-europejskiej-2-jak-powstala-unia/) | yes, in the article lead (browser; the lead is written with non-breaking spaces) | supports | yes; the product shows 24.05.2024, the page says 02.05.2024 |
| 8 | A01 | potwierdzone | [PAP](https://www.pap.pl/aktualnosci/26-lat-polski-w-sojuszu-polnocnoatlantyckim-jakie-wyzwania-staly-przed-naszym-krajem) | not checked: the page renders blank in an automated browser and the raw fetch is a script shell; the product labelled it a search-result fragment | — | not checked; the claim rests on four other sources too (IPN, BBN, KPRP, NATO) |
| 9 | FC-A04 | potwierdzone | [PAP / Eurostat](https://europapnews.pap.pl/eurostat-41-mln-osob-z-ukrainy-objetych-tymczasowa-ochrona-w-ue) | yes, word for word (raw page) | supports: Germany had the most people under temporary protection | partly: the figure is for the end of July 2024 and the claim names April 2024, so the page does not support the claim's time scope; not counted as verified support |
| 10 | B01 | wprowadzające w błąd | [Demagog](https://demagog.org.pl/wypowiedzi/protesty-we-francji-berkowicz-udostepnia-stare-nagranie/) | yes, word for word (browser); the page's rating is "Manipulacja" | names the missing context: the video is from March 2023 | yes |
| 11 | C02 | wprowadzające w błąd | [Kancelaria Sejmu](https://api.sejm.gov.pl/sejm/term10/interpellations/19063/body) | yes, word for word (raw page) | context: an MP notes that the announcement listed no towns, dates or lines | yes |
| 12 | FC-B06 | wprowadzające w błąd | [Demagog](https://demagog.org.pl/wypowiedzi/donald-tusk-okresla-sie-rzecznikiem-interesow-izraela-to-niepelny-cytat/) | the rating "Manipulacja" is in the page's ClaimReview markup, dated 2025-09-26 (browser) | an incomplete quote | yes |

## Result

- **Quote or rating on the page:** 11 of 12. The twelfth page (A01) could not be read by any automated method.
- **Fits the verdict shown:** 9 of 12. FC-I03 fits only partly, by design: a disinformation database is context, not
  proof. FC-A04 fits only partly: the figure is for another month than the claim. A01 was not checked.
- **Dates:** in 2 of the 11 checked, the product shows a date other than the page's publication date (I03, A02).
  It probably takes the page's modification date. This is open work.
- **Time scope:** in 1 of the 11 (FC-A04), the source supports the claim for another month than the claim names.

The sample is small, and the run is one run: see [HISTORY.md](HISTORY.md) for how the metrics vary between runs.
