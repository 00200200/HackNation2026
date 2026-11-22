# Konspekt prezentacji

Tekst roboczy do PDF, zgodnie z [issue #18](https://github.com/00200200/HackNation2026/issues/18).
Limit: 12 slajdów; poniższy konspekt ma 12 slajdów. Liczby wyników pochodzą z
[evals/results/latest.json](../../evals/results/latest.json), a gdzie napisano inaczej (slajdy 9 i 10), z wiersza
`edd34a5` w HISTORY.md na `integration/r3`; pełna tabela i opis pomiaru są w
[architecture.md](architecture.md). Koszty na slajdzie 9 i ich źródła są w [cost.md](cost.md).
PDF i film nie są częścią tego pliku.

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

- Równolegle: Google Fact Check Tools, wyszukiwarka www.gov.pl, Tavily, EUvsDisinfo MCP i zamknięty korpus (BM25 w pamięci, #74).
- Fragmenty są porządkowane, a cytaty sprawdzane z pobranym tekstem. Reguły w kodzie ustalają ocenę.
- EUvsDisinfo daje kontekst; własna baza PostgreSQL ze źródłami (#19) jest wyłączona; to nie korpus dowodów z poprzedniej linii.
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

- Zapisany szybki test na `95e6177`: `median_latency_s: 3.8964525419287384`,
  `cost_per_100_usd: 1.8220444444444441`. Ta wersja wołała model raz, tylko do wyodrębnienia
  twierdzeń, bez sędziego i bez Tavily. 1,82 USD za 100 to więc koszt samego wyodrębniania.
- Pełny potok, szybki przebieg `edd34a5` na 10 przypadkach (Opus, przed #95): modele 0,0491 USD, a 100
  testów to 4,91 USD plus do 3,90 USD za Tavily. Obecny kod może kosztować więcej albo mniej (#95 podnosi
  koszt, #88 go obniża). Do tego około 4,9 kredytu Tavily na sprawdzenie (przebieg z 21.11). Konto
  Tavily: plan Researcher z opłatą za zużycie, 1000 kredytów za darmo (UNCONFIRMED), potem 0,008 USD.
  Szacunek: 1000 sprawdzeń kosztuje 80,10 USD, czyli 325 zł. Limit konta (4000 kredytów) starcza na
  820 do 1025 sprawdzeń, zależnie od tego, czy wlicza darmowe kredyty (UNCONFIRMED). Mediana 24,9 s na
  `edd34a5`; przebieg ze stagingu na Sonnecie 5.5 (README, bez wiersza w HISTORY.md): 18,3 s.
  Obywatel płaci 0 zł.
- Serwer i domena: około 42,77 zł miesięcznie. Zachowania pod obciążeniem nie mierzyliśmy (#88).
  Ostateczne liczby: z pełnego evalu (#16). [Założenia i rachunek](cost.md).

## Slajd 10. Bezpieczeństwo i prywatność

- Kod oddziela dane od instrukcji, sprawdza obecność cytatów i ogranicza pobieranie podanych URL.
- Maskowanie danych osobowych (e-mail, IBAN/NRB, karta, PESEL, telefon) działa przed modelem i w
  każdym logu; dziennik sprawdzeń trzyma maskowany zapis 30 dni, sesję można usunąć (`DELETE
  /api/sessions/{id}`, przycisk na stronie). Imiona i adresy nie są wykrywane.
  [Prywatność](../privacy.md).
- W `latest.json` (`95e6177`) `injection_resistance: 0.0` (nie spełnia progu). Nowszy przebieg `edd34a5`
  (HISTORY.md na `integration/r3`, 10 przypadków, E05 i E06 pominięte, macro-F1 0,278) ma 1.0. Przypadków
  jest za mało, to nie dowód odporności ([latest.json](../../evals/results/latest.json)). Discord nie ma jeszcze komendy usuwania.
  [Ryzyka z odwołaniami do kodu](risks.md).

## Slajd 11. Ograniczenia

- DuckDuckGo zastąpiono Tavily po problemach z wynikami. Korpus 1158 dokumentów jest zbudowany i w buildzie `integration/r3`
  podpięty do sprawdzania (#74), ale nie zmierzyliśmy jego wpływu na jakość.
- Baza incydentów organizatora jest wpięta, ale pusta (plik od organizatora jeszcze nie dotarł).
- Prawa do przechowywania wybranych treści wymagają rozstrzygnięcia; w Discordzie brak komendy usuwania sesji.
- Nie pokazujemy rozpoznawania obrazów ani kolejki moderatora jako gotowych funkcji.
  [Stan projektu](../../WORKLOG.md), [źródła](sources.md), [architektura](architecture.md).

## Slajd 12. Następne kroki i materiały do oddania

- Uruchomić skuteczne wyszukiwanie na zatwierdzonych źródłach i poprawić błędy ujawnione w teście.
- Zmierzyć poprawność cytatów i zgodność kanałów; sprawdzić ochronę danych oraz obciążenie.
- Uzupełnić TEAM_NAME. Człowiek przygotowuje PDF i film zgodnie z limitami w
  [issue #18](https://github.com/00200200/HackNation2026/issues/18); zgłoszenie wymaga akceptacji zespołu.
