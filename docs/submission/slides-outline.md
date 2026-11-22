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

- Równolegle: Google Fact Check Tools, Perplexity Search API i EUvsDisinfo MCP.
- Fragmenty są porządkowane, a cytaty sprawdzane z pobranym tekstem. Reguły w kodzie ustalają ocenę.
- EUvsDisinfo daje kontekst; własna baza PostgreSQL jest wyłączona.
  [Architektura](architecture.md), [źródła i prawa do wykorzystania](sources.md).

## Slajd 6. Plan pokazu

- Wkleić nowe twierdzenie, poczekać na odpowiedź i otworzyć wskazane źródło, jeśli jest dostępne.
- Pokazać cytat obok przesłanki oraz komunikat o braku źródeł lub awarii, gdy wystąpi.
- Powtórzyć zapytanie przez Discord po skonfigurowaniu bota. To plan pokazu, nie zapis udanego testu.
  [Uruchomienie](../../README.md#run).

## Slajd 7. Zapisany test

- Szybki test regresji, nie pełny test: `n_cases: 9`, `dirty: false`, `coverage_ok: true`, `overall_pass: false`.
- Commit produktu: `95e6177b5f2ff53f85d222c2cb721630b7b14ebd`, sprzed scalenia #40 z `main`; świeży test po
  scaleniu jeszcze nie uruchomiony (decyzja: `HN_SKIP_EVAL=1`).
- Znacznik czasu: `2026-11-21T19:10:57+00:00`.
- Źródło wszystkich wartości: [latest.json](../../evals/results/latest.json).

## Slajd 8. Wyniki jakości

- `macro_f1: 0.1`; `citation_coverage: null`; `abstention: 1.0`.
- `injection_resistance: 0.0`; `end_to_end: 0.8888888888888888`.
- `citation_correctness: null`; `channel_consistency: null`: niezmierzone.
- Wynik całości nie spełnia wymagań. Pokrycie cytatami nie dowodzi poprawności interpretacji.
  [Dokładne wyniki i definicje](architecture.md#saved-test-results-and-reproduction),
  [plik pomiaru](../../evals/results/latest.json).

## Slajd 9. Czas i koszt

- `median_latency_s: 3.8964525419287384`; `cost_per_100_usd: 1.8220444444444441`.
- Ekstrapolacja: `1.8220444444444441 / 100 * 1000 = 18.220444444444441 USD`, czyli około
  `18.22 USD` za 1000 sprawdzeń przy tej samej mieszance zapytań.
- Źródło: [latest.json](../../evals/results/latest.json). Hosting, opłaty kanału i zachowanie pod
  obciążeniem: UNCONFIRMED. [Założenia i rachunek](cost.md).

## Slajd 10. Bezpieczeństwo i prywatność

- Kod oddziela dane od instrukcji, sprawdza obecność cytatów i ogranicza pobieranie podanych URL.
- Maskowanie danych osobowych (e-mail, IBAN/NRB, karta, PESEL, telefon) działa przed modelem i w
  każdym logu; dziennik sprawdzeń trzyma maskowany zapis 30 dni, sesję można usunąć (`DELETE
  /api/sessions/{id}`, przycisk na stronie). Imiona i adresy nie są wykrywane.
  [Prywatność](../privacy.md).
- Najnowszy zapisany test `injection_resistance: 0.0` (nie spełnia progu); wcześniejszy test na
  innym commicie przechodził. Oba obejmują jeden przypadek, to nie dowód odporności
  ([latest.json](../../evals/results/latest.json)). Discord nie ma jeszcze komendy usuwania.
  [Ryzyka z odwołaniami do kodu](risks.md).

## Slajd 11. Ograniczenia

- DuckDuckGo zastąpiono Tavily po problemach z wynikami; korpus demonstracyjny nadal nie jest zbudowany.
- Baza incydentów organizatora jest wpięta, ale pusta (plik od organizatora jeszcze nie dotarł).
- Prawa do przechowywania wybranych treści wymagają rozstrzygnięcia; w Discordzie brak komendy usuwania sesji.
- Nie pokazujemy rozpoznawania obrazów ani kolejki moderatora jako gotowych funkcji.
  [Stan projektu](../../WORKLOG.md), [źródła](sources.md), [architektura](architecture.md).

## Slajd 12. Następne kroki i materiały do oddania

- Uruchomić skuteczne wyszukiwanie na zatwierdzonych źródłach i poprawić błędy ujawnione w teście.
- Zmierzyć poprawność cytatów i zgodność kanałów; sprawdzić ochronę danych oraz obciążenie.
- Uzupełnić TEAM_NAME. Człowiek przygotowuje PDF i film zgodnie z limitami w
  [issue #18](https://github.com/00200200/HackNation2026/issues/18); zgłoszenie wymaga akceptacji zespołu.
