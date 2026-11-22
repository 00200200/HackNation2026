# Konspekt prezentacji

Tekst roboczy do PDF, zgodnie z [issue #18](https://github.com/00200200/HackNation2026/issues/18).
Limit: 12 slajdów; poniższy konspekt ma 12 slajdów. Liczby wyników pochodzą z pełnego
przebiegu na `ca48b84` (wiersz w [HISTORY.md](../../evals/results/HISTORY.md) i plik JSON
`evals/results/history/20261122T021757.182695Z-ca48b84-full.json`, oba w commitach PR #123). Starszy `latest.json` na `main` to `95e6177`. Pełna tabela i opis pomiaru są w
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

- Pełny test: `mode: full`, `n_cases: 75`, `dirty: false`, `coverage_ok: true`, `overall_pass: false`.
  Pominięte, bez oceny: E05-E15 (11 przypadków), bo brakowało publicznego adresu strony z fixture.
- Commit produktu: `ca48b84390d0df22881024155a37bfafba606ce2` (`integration/r3`). To nie jest jeszcze commit
  zgłoszenia: świeży pełny test na nim ([z #16]) dopiero wykonamy.
- Znacznik czasu: `2026-11-22T02:27:29+00:00`.
- Źródło wszystkich wartości: wiersz `ca48b84` w HISTORY.md i plik JSON tego przebiegu.

## Slajd 8. Wyniki jakości

- `macro_f1: 0.803` (próg 0,75); `abstention: 0.917` (0,80); `injection_resistance: 1.0` (0,90).
- `citation_coverage: 1.0` (0,95); `citation_correctness: 1.0` (0,85); `channel_consistency: 1.0` (1,0).
  Uwaga: `citation_correctness` sprawdza tylko, czy cytat z dokumentu korpusu występuje w nim dosłownie, a nie
  czy wspiera tezę. `channel_consistency` pokazuje, że wspólna pamięć wyników (#59, TTL 30 minut) oddaje na
  Discordzie zapisaną odpowiedź ze strony, a nie że dwa niezależne sprawdzenia się zgadzają.
- Poniżej progu: `end_to_end: 0.973` (1,0) i `moderator_loop: 0.0` (1,0; pętli moderatora nie zbudowaliśmy, #79).
- Wynik całości nie spełnia wymagań. Odporność na polecenia dotyczy 7 przypadków E, bo 11 z ukrytym
  poleceniem w stronie pominięto. Poprawność cytatów to występowanie cytatu w źródle, a nie ocena
  interpretacji. To jeden przebieg na naszym zestawie, a nie wynik na zbiorze jury.
  [Dokładne wyniki i definicje](architecture.md#saved-test-results-and-reproduction).

## Slajd 9. Czas i koszt

- Pełny przebieg na `ca48b84`: `median_latency_s: 17.84` (próg 30 s), `cost_per_100_usd: 4.27`
  (średnia z 71 odpowiedzi z ceną, bez czterech symulowanych awarii). To kod `integration/r3` z #88, #95 i #74.
  Modele: 0,0427 USD za sprawdzenie, a 100 testów to 4,27 USD plus około 3,90 USD za Tavily
  (szacunek). Wcześniejsze pomiary: 1,82 USD za 100 na `95e6177` (jedno wywołanie modelu, bez sędziego
  i bez Tavily) i 4,91 USD na `edd34a5` (Opus, przed #95). Do tego około 4,9 kredytu Tavily na sprawdzenie (przebieg z 21.11). Konto
  Tavily: plan Researcher z opłatą za zużycie, 1000 kredytów za darmo (UNCONFIRMED), potem 0,008 USD.
  Szacunek: 1000 sprawdzeń kosztuje 73,70 USD, czyli 299 zł. Limit konta (4000 kredytów) starcza na
  820 do 1025 sprawdzeń, zależnie od tego, czy wlicza darmowe kredyty (UNCONFIRMED). Wcześniej mediana 24,9 s na
  `edd34a5` (10 przypadków).
  Obywatel płaci 0 zł.
- Serwer i domena: około 42,77 zł miesięcznie. Zachowania pod obciążeniem nie mierzyliśmy (#88).
  Ostateczne liczby: z pełnego evalu (#16). [Założenia i rachunek](cost.md).

## Slajd 10. Bezpieczeństwo i prywatność

- Kod oddziela dane od instrukcji, sprawdza obecność cytatów i ogranicza pobieranie podanych URL.
- Maskowanie danych osobowych (e-mail, IBAN/NRB, karta, PESEL, telefon) działa przed modelem i w
  każdym logu; dziennik sprawdzeń trzyma maskowany zapis 30 dni, sesję można usunąć (`DELETE
  /api/sessions/{id}`, przycisk na stronie). Imiona i adresy nie są wykrywane.
  [Prywatność](../privacy.md).
- W `latest.json` na `main` (`95e6177`) `injection_resistance: 0.0` (nie spełnia progu). Pełny przebieg
  na `ca48b84` (HISTORY.md, 75 przypadków, E05-E15 pominięte) ma 1.0, ale dotyczy 7 przypadków E. To nie
  dowód odporności, bo przypadki z poleceniem ukrytym w stronie nie były oceniane. Discord nie ma jeszcze komendy usuwania.
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
- Zmierzyć, czy cytat wspiera tezę (dziś mierzymy tylko jego obecność w źródle), wpływ korpusu na odpowiedzi i zgodność kanałów bez wspólnej pamięci wyników; sprawdzić ochronę danych oraz obciążenie.
- Uzupełnić TEAM_NAME. Człowiek przygotowuje PDF i film zgodnie z limitami w
  [issue #18](https://github.com/00200200/HackNation2026/issues/18); zgłoszenie wymaga akceptacji zespołu.
