# Konspekt prezentacji

Tekst roboczy do PDF, zgodnie z [issue #18](https://github.com/00200200/HackNation2026/issues/18).
Limit: 12 slajdów; poniższy konspekt ma 12 slajdów. Liczby wyników pochodzą z pełnego przebiegu na `ca48b84`
([plik](https://github.com/00200200/HackNation2026/blob/6126ac9ea3b750704006d320fe095ed9413505d5/evals/results/history/20261122T021757.182695Z-ca48b84-full.json)); pełna tabela i opis pomiaru są w
[architecture.md](architecture.md). PDF i film nie są częścią tego pliku. [PR #126](https://github.com/00200200/HackNation2026/pull/126) dodaje `docs/pitch/faktczyfejk-pitch.pdf` (12 stron); konspektu nie porównywano z jej treścią, więc liczby i opisy mogą się różnić.

## Slajd 1. Prawdowid

- TEAM_NAME
- Sprawdź twierdzenie i zobacz źródła.
- Prototyp dla zadania MSZ. Wynik obejmuje ocenę oraz jej ograniczenia.

## Slajd 2. Problem

- Wiadomość może łączyć sprawdzalne fakty z opinią albo pomijać kontekst.
- Prawdowid rozdziela twierdzenia i pokazuje, na jakiej podstawie można je ocenić.
- Gdy zabraknie materiałów, użytkownik powinien zobaczyć tę lukę. [Podstawa działania](architecture.md).

## Slajd 3. Odbiorcy

- Planowany odbiorca: osoba, która chce sprawdzić wiadomość przed jej udostępnieniem.
- Formularz WWW i komenda Discord /sprawdz wywołują tę samą usługę.
- Badania użytkowników i działanie na prawdziwym Discordzie: niepotwierdzone.
  [Stan projektu](../../WORKLOG.md).

## Slajd 4. Od tekstu do twierdzeń

- Wklejony tekst albo publiczny link HTML/PDF trafia do API.
- Model wyodrębnia twierdzenia i pytania do wyszukiwarki; opinie mają osobne oznaczenie.
- Podany link nie jest dowodem dla własnych twierdzeń. [Przepływ danych](architecture.md).

## Slajd 5. Wyszukiwanie i ocena

- Równolegle: Google Fact Check Tools, wyszukiwarka www.gov.pl, Tavily i EUvsDisinfo MCP; po scaleniu [PR #126](https://github.com/00200200/HackNation2026/pull/126) także nasz korpus dowodowy (BM25 w pamięci).
- Fragmenty są porządkowane, a cytaty sprawdzane z pobranym tekstem. Reguły w kodzie ustalają ocenę.
- EUvsDisinfo daje kontekst; własna baza PostgreSQL jest wyłączona.
  [Architektura](architecture.md), [źródła i prawa do wykorzystania](sources.md).

## Slajd 6. Plan pokazu

- Wkleić nowe twierdzenie, poczekać na odpowiedź i otworzyć wskazane źródło, jeśli jest dostępne.
- Pokazać cytat obok przesłanki oraz komunikat o braku źródeł lub awarii, gdy wystąpi.
- Powtórzyć zapytanie przez Discord po skonfigurowaniu bota. To plan pokazu, nie zapis udanego testu.
  [Uruchomienie](../../README.md#run).

## Slajd 7. Zapisany test

- Pełny test, 75 z 86 przypadków: `mode: full`, `n_cases: 75`, `dirty: false`, `coverage_ok: true`,
  `overall_pass: false`. E05 do E15 pominięte (brak publicznego adresu stron testowych).
- Commit zapisany w pliku: `ca48b84390d0df22881024155a37bfafba606ce2`, głowa [PR #126](https://github.com/00200200/HackNation2026/pull/126), jeszcze nie na `main`. Plik wyniku
  ([przebieg pełny](https://github.com/00200200/HackNation2026/blob/6126ac9ea3b750704006d320fe095ed9413505d5/evals/results/history/20261122T021757.182695Z-ca48b84-full.json)) jest w [PR #128](https://github.com/00200200/HackNation2026/pull/128) i
  [PR #123](https://github.com/00200200/HackNation2026/pull/123), nie w PR #126. Test objął ekstrakcję, wyszukiwanie, reranking i
  sędziego; plik nie zapisuje modelu ekstrakcji, miejsca uruchomienia ani commitu serwera (pole `commit` to checkout, z którego uruchomiono harness).
- Znacznik czasu: `2026-11-22T02:27:29+00:00`.
- Na `main` leży starszy test z commita `95e6177`, wykonany na szkielecie sprzed sędziego ([plik](https://github.com/00200200/HackNation2026/blob/1aa173f6e651f7ff2bdacebb2d4384658efc2d48/evals/results/latest.json)): weryfikator
  zwracał stałe `brak wystarczających dowodów`. Jego wartości nie opisują produktu i nie są tu
  cytowane ([eval-notes](../eval-notes.md), [README, sekcja metryk](../../README.md#metryki-obowiązkowe-sekcja-6)).
- Pełny test zastąpił szybkie testy na 10 przypadkach (`edd34a5`, [plik](https://github.com/00200200/HackNation2026/blob/ca48b84390d0df22881024155a37bfafba606ce2/evals/results/latest.json); `ca48b84`, [plik](https://github.com/00200200/HackNation2026/blob/cd61db592e81aa7b22a24690cb090d64116d17dd/evals/results/history/20261122T021403.618691Z-ca48b84-quick.json)). Liczby na
  slajdach 8 do 10 pochodzą tylko z pełnego testu.

## Slajd 8. Wyniki jakości

- `macro_f1: 0.8026992266992267` (próg co najmniej 0.75, spełniony): poprawny werdykt w 55 z 69 przypadków
  z werdyktem wzorcowym.
- `citation_coverage: 1.0` (próg 0.95; co najmniej 52 twierdzenia, plik nie zapisuje mianownika);
  `citation_correctness: 1.0` (próg 0.85; cytaty z dokumentów korpusu występują dosłownie w ich tekście, bez ręcznej próbki);
  `abstention: 0.9166666666666666` (próg 0.8; 11 z 12, pudło FC-D02).
- `injection_resistance: 1.0` (7 przypadków z wstrzyknięciem w tekście wejściowym; wstrzyknięć w stronach, E05 do E15,
  nie oceniano, więc to nie dowód odporności na nie); `channel_consistency: 1.0` (6 przypadków).
- `end_to_end: 0.9733333333333334` (próg 1.0, niespełniony): J01 (symulowana awaria Fact Check) dał werdykt `potwierdzone`, a wzorzec nie
  dopuszcza werdyktu faktograficznego; A15 (pytanie o opinię) dał `needs_clarification` zamiast odpowiedzi `ok`. Według opisu
  PR #126 w J01 odpowiedź ujawnia awarię, ale daje werdykty z innych źródeł (decyzja zespołu,
  [#101](https://github.com/00200200/HackNation2026/issues/101)). `moderator_loop: 0.0`: niezbudowany.
- Wynik całości nie spełnia wymagań (`overall_pass: false`). Pokrycie cytatami i obecność cytatu w tekście nie dowodzą poprawności
  interpretacji, a wartości liczą się na 75 przypadkach naszego zestawu.
  [Dokładne wyniki i definicje](architecture.md#saved-test-results-and-reproduction),
  [plik pomiaru](https://github.com/00200200/HackNation2026/blob/6126ac9ea3b750704006d320fe095ed9413505d5/evals/results/history/20261122T021757.182695Z-ca48b84-full.json).

## Slajd 9. Czas i koszt

- `median_latency_s: 17.842587917002675` (próg najwyżej 30 s) obejmuje cały potok: ekstrakcję, wyszukiwanie,
  reranking i sędziego. 8 z 75 odpowiedzi trwało dłużej niż 30 s, najwolniejszy przypadek, D03, 38.6 s; dwa przypadki z adresem URL:
  U01 28.5 s, U02 27.8 s. `cost_per_100_usd: 4.272704084507042` (wywołania modeli z 71 wycenionych odpowiedzi; 4 przypadki z symulowaną awarią pominięto).
- Ekstrapolacja: `4.272704084507042 / 100 * 1000 = 42.72704084507042 USD`, czyli około `42.73 USD` za 1000 sprawdzeń, przy mieszance
  przypadków naszego zestawu. Model ekstrakcji pełnego przebiegu nie jest zapisany w pliku: UNCONFIRMED. Starsze przebiegi na 10
  przypadkach dały 4.91 USD za 100 (`edd34a5`, Opus) i 5.54 USD za 100 (`ca48b84`, szybki). Kwota 3.96 USD z Sonnetem pochodzi z opisu
  PR #126 (komunikat commita `83d6c65` ma te liczby bez pierwszej cyfry kosztu), a pliku tego przebiegu nie zapisano: UNCONFIRMED.
- Źródło: [plik pełnego przebiegu](https://github.com/00200200/HackNation2026/blob/6126ac9ea3b750704006d320fe095ed9413505d5/evals/results/history/20261122T021757.182695Z-ca48b84-full.json). Hosting, opłaty kanałów, wyszukiwanie i
  zachowanie pod obciążeniem: UNCONFIRMED. [Założenia i rachunek](cost.md).

## Slajd 10. Bezpieczeństwo i prywatność

- Kod oddziela dane od instrukcji, sprawdza obecność cytatów i ogranicza pobieranie podanych URL. W [PR #126](https://github.com/00200200/HackNation2026/pull/126)
  treść pobranych stron jest też sprawdzana w kodzie pod kątem wstrzykniętych instrukcji ([#61](https://github.com/00200200/HackNation2026/issues/61),
  [#62](https://github.com/00200200/HackNation2026/issues/62)); na `main` reranker i model sędziego czytają źródła, wstrzyknięcie w źródle może zgłosić tylko sędzia, a kod źródeł nie przeszukuje.
- Maskowanie danych osobowych (e-mail, IBAN/NRB, karta, PESEL, telefon; w PR #126 także numer dowodu i
  paszportu, a numer karty po etykiecie produktu, na przykład `nr`, zostaje bez maski) działa przed modelem i w każdym logu; dziennik sprawdzeń trzyma maskowany zapis 30 dni, sesję
  można usunąć (`DELETE /api/sessions/{id}`, przycisk na stronie). Imiona i adresy nie są wykrywane.
  [Prywatność](../privacy.md).
- Zapisany pełny test (`ca48b84`) ma `injection_resistance: 1.0` na 7 przypadkach z wstrzyknięciem w tekście wejściowym
  (E01 do E04, FC-E01 do FC-E03); wstrzyknięć w stronach (E05 do E15) nie oceniano, więc to nie dowód odporności. Starszy test
  na `main` (szkielet z commita `95e6177`) pokazuje 0.0 ([plik](https://github.com/00200200/HackNation2026/blob/1aa173f6e651f7ff2bdacebb2d4384658efc2d48/evals/results/latest.json),
  [HISTORY.md](../../evals/results/HISTORY.md)). Discord nie ma jeszcze komendy usuwania.
  [Ryzyka z odwołaniami do kodu](risks.md).

## Slajd 11. Ograniczenia

- DuckDuckGo zastąpiono Tavily po problemach z wynikami. Nasz korpus dowodowy (1158 rekordów) jest
  przeszukiwany w sprawdzeniu dopiero po scaleniu [PR #126](https://github.com/00200200/HackNation2026/pull/126) ([#74](https://github.com/00200200/HackNation2026/issues/74)); na `main` leży tylko w repozytorium.
- Część opisanych funkcji jest w otwartych PR i jeszcze nie na `main`:
  [lista w README](../../README.md#zmiany-czekające-na-scalenie).
- Baza incydentów organizatora jest wpięta, ale pusta (plik od organizatora jeszcze nie dotarł).
- Prawa do przechowywania wybranych treści wymagają rozstrzygnięcia; w Discordzie brak komendy usuwania sesji.
- Nie pokazujemy rozpoznawania obrazów ani kolejki moderatora jako gotowych funkcji.
  [Stan projektu](../../WORKLOG.md), [źródła](sources.md), [architektura](architecture.md).

## Slajd 12. Następne kroki i materiały do oddania

- Uruchomić skuteczne wyszukiwanie na zatwierdzonych źródłach i poprawić błędy ujawnione w teście.
- Sprawdzić ręcznie próbkę cytatów (policzono tylko ich obecność w tekście dokumentu) i zgodność z żywym Discordem; sprawdzić ochronę
  danych oraz obciążenie.
- Uzupełnić TEAM_NAME. Człowiek przygotowuje PDF i film zgodnie z limitami w
  [issue #18](https://github.com/00200200/HackNation2026/issues/18); zgłoszenie wymaga akceptacji zespołu.
