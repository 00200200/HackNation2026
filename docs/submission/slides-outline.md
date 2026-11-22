# Konspekt prezentacji

Tekst roboczy do PDF, zgodnie z [issue #18](https://github.com/00200200/HackNation2026/issues/18).
Limit: 12 slajdów; poniższy konspekt ma 12 slajdów. Liczby wyników pochodzą z
[evals/results/latest.json](../../evals/results/latest.json); pełna tabela i opis pomiaru są w
[architecture.md](architecture.md). PDF i film nie są częścią tego pliku.

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

- Równolegle: Google Fact Check Tools, wyszukiwarka www.gov.pl, Tavily i EUvsDisinfo MCP; po scaleniu [PR #109](https://github.com/00200200/HackNation2026/pull/109) także nasz korpus dowodowy (BM25 w pamięci).
- Fragmenty są porządkowane, a cytaty sprawdzane z pobranym tekstem. Reguły w kodzie ustalają ocenę.
- EUvsDisinfo daje kontekst; własna baza PostgreSQL jest wyłączona.
  [Architektura](architecture.md), [źródła i prawa do wykorzystania](sources.md).

## Slajd 6. Plan pokazu

- Wkleić nowe twierdzenie, poczekać na odpowiedź i otworzyć wskazane źródło, jeśli jest dostępne.
- Pokazać cytat obok przesłanki oraz komunikat o braku źródeł lub awarii, gdy wystąpi.
- Powtórzyć zapytanie przez Discord po skonfigurowaniu bota. To plan pokazu, nie zapis udanego testu.
  [Uruchomienie](../../README.md#run).

## Slajd 7. Zapisany test

- Szybki test regresji, nie pełny test: `n_cases: 10`, `dirty: false`, `coverage_ok: true`,
  `overall_pass: false`. Po jednym przypadku ze scenariuszy A, B, C, D, E, G, H, I, J i U; E05 i E06
  pominięte (brak publicznego adresu stron testowych).
- Commit produktu: `edd34a5d2dd7f15515e27f51fa06bc2f1c4b3acb`, w [PR #109](https://github.com/00200200/HackNation2026/pull/109), jeszcze nie na `main`. Test objął
  ekstrakcję, wyszukiwanie, reranking i sędziego; ekstrakcja działała na Opusie (według opisu commita
  `83d6c65`, plik tego nie zapisuje).
- Na `main` leży starszy test z commita `95e6177`, wykonany na szkielecie sprzed sędziego (weryfikator
  zwracał stałe `brak wystarczających dowodów`). Jego wartości nie opisują produktu i nie są tu
  cytowane ([eval-notes](../eval-notes.md), [README, sekcja metryk](../../README.md#metryki-obowiązkowe-sekcja-6)).
- Znacznik czasu: `2026-11-22T00:37:27+00:00`.
- Źródło wartości na slajdach 8 do 10: [latest.json](../../evals/results/latest.json) z PR #109.

## Slajd 8. Wyniki jakości

- `macro_f1: 0.2777777777777778` (próg co najmniej 0.75, niespełniony): poprawny werdykt w 4 z 10 przypadków.
- `citation_coverage: 1.0` (jeden przypadek, E01); `abstention: 1.0` (dwa przypadki, D01 i H01).
- `injection_resistance: 1.0` (jeden przypadek, E01: wstrzyknięcie w tekście; wstrzyknięć w stronach nie
  liczono); `channel_consistency: 1.0` (jeden przypadek, G01).
- `end_to_end: 0.9` (próg 1.0, niespełniony): przypadek J01 (symulowana awaria Fact Check) dał `nie sprawdzono`
  w odpowiedzi `ok` zamiast `technical_error` ([#101](https://github.com/00200200/HackNation2026/issues/101)). `moderator_loop: 0.0`: niezbudowany.
  `citation_correctness: null`: niezmierzone.
- Wynik całości nie spełnia wymagań, a każdy współczynnik opiera się na jednym lub dwóch przypadkach, więc
  żaden nie jest dowodem. Pokrycie cytatami nie dowodzi poprawności interpretacji.
  [Dokładne wyniki i definicje](architecture.md#saved-test-results-and-reproduction),
  [plik pomiaru](../../evals/results/latest.json).

## Slajd 9. Czas i koszt

- `median_latency_s: 24.877917104000517` (próg najwyżej 30 s) obejmuje cały potok: ekstrakcję, wyszukiwanie,
  reranking i sędziego. Najwolniejszy przypadek, U01, trwał 37.4 s. `cost_per_100_usd: 4.912332` (wywołania
  modeli, ekstrakcja na Opusie).
- Ekstrapolacja: `4.912332 / 100 * 1000 = 49.12332 USD`, czyli około `49.12 USD` za 1000 sprawdzeń, przy tej
  samej mieszance zapytań. Z Sonnetem jako modelem ekstrakcji około 3.96 USD za 100 i mediana 18.3 s według
  opisu commita `83d6c65`; pliku tego przebiegu nie zapisano: UNCONFIRMED.
- Źródło: [latest.json](../../evals/results/latest.json) z PR #109. Hosting, opłaty kanałów, wyszukiwanie i
  zachowanie pod obciążeniem: UNCONFIRMED. [Założenia i rachunek](cost.md).

## Slajd 10. Bezpieczeństwo i prywatność

- Kod oddziela dane od instrukcji, sprawdza obecność cytatów i ogranicza pobieranie podanych URL. W [PR #109](https://github.com/00200200/HackNation2026/pull/109)
  treść pobranych stron jest też sprawdzana pod kątem wstrzykniętych instrukcji ([#61](https://github.com/00200200/HackNation2026/issues/61),
  [#62](https://github.com/00200200/HackNation2026/issues/62)).
- Maskowanie danych osobowych (e-mail, IBAN/NRB, karta, PESEL, telefon; w PR #109 także numer dowodu i
  paszportu) działa przed modelem i w każdym logu; dziennik sprawdzeń trzyma maskowany zapis 30 dni, sesję
  można usunąć (`DELETE /api/sessions/{id}`, przycisk na stronie). Imiona i adresy nie są wykrywane.
  [Prywatność](../privacy.md).
- Test z PR #109 ma `injection_resistance: 1.0` na jednym przypadku (E01, wstrzyknięcie w tekście
  wejściowym); wstrzyknięć w stronach (E05 do E15) nie oceniano, więc to nie dowód odporności. Starszy test
  na `main` (szkielet z commita `95e6177`) pokazuje 0.0 ([latest.json](../../evals/results/latest.json),
  [HISTORY.md](../../evals/results/HISTORY.md)). Discord nie ma jeszcze komendy usuwania.
  [Ryzyka z odwołaniami do kodu](risks.md).

## Slajd 11. Ograniczenia

- DuckDuckGo zastąpiono Tavily po problemach z wynikami. Nasz korpus dowodowy (1158 rekordów) jest
  przeszukiwany w sprawdzeniu dopiero po scaleniu [PR #109](https://github.com/00200200/HackNation2026/pull/109) ([#74](https://github.com/00200200/HackNation2026/issues/74)); na `main` leży tylko w repozytorium.
- Część opisanych funkcji jest w otwartych PR i jeszcze nie na `main`:
  [lista w README](../../README.md#zmiany-czekające-na-scalenie).
- Baza incydentów organizatora jest wpięta, ale pusta (plik od organizatora jeszcze nie dotarł).
- Prawa do przechowywania wybranych treści wymagają rozstrzygnięcia; w Discordzie brak komendy usuwania sesji.
- Nie pokazujemy rozpoznawania obrazów ani kolejki moderatora jako gotowych funkcji.
  [Stan projektu](../../WORKLOG.md), [źródła](sources.md), [architektura](architecture.md).

## Slajd 12. Następne kroki i materiały do oddania

- Uruchomić skuteczne wyszukiwanie na zatwierdzonych źródłach i poprawić błędy ujawnione w teście.
- Zmierzyć poprawność cytatów i zgodność kanałów; sprawdzić ochronę danych oraz obciążenie.
- Uzupełnić TEAM_NAME. Człowiek przygotowuje PDF i film zgodnie z limitami w
  [issue #18](https://github.com/00200200/HackNation2026/issues/18); zgłoszenie wymaga akceptacji zespołu.
