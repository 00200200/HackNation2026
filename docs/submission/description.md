# Opis zgłoszenia

Nazwa zespołu: Genwrownik

Tytuł: faktczyfejk.pl: sprawdź, zanim podasz dalej

## Opis do formularza

Na https://faktczyfejk.pl wklejasz tekst albo link, bez konta i za darmo, i dostajesz po polsku ocenę twierdzeń z uzasadnieniem, ograniczeniami i źródłami. Myśleliśmy o osobie słabo znającej technologię i o analityku MSZ, który musi wiedzieć, skąd wzięła się ocena.

Ocen jest pięć: potwierdzone, fałszywe, wprowadzające w błąd, brak wystarczających dowodów i nie podlega weryfikacji. Osobno, nigdy jako ocenę, pokazujemy „nie sprawdzono”, błąd techniczny, stronę, której nie da się sprawdzić (paywall, logowanie), i prośbę o doprecyzowanie. „Nie sprawdzono” z powodem dostaje twierdzenie, gdy nie odpowie model, czas minie przed oceną albo padnie źródło zdolne rozstrzygnąć (Fact Check, wyszukiwarka, w sprawach rządu gov.pl), a innych dowodów brak. Awaria przy wszystkich twierdzeniach daje komunikat techniczny.

Claude dzieli tekst na twierdzenia, a trzy najważniejsze sprawdzamy w pełni. Dla każdego równolegle przeszukujemy Google Fact Check Tools, wyszukiwanie w sieci (Perplexity, a bez jego klucza Tavily) na wybranych domenach, www.gov.pl, EUvsDisinfo (tylko kontekst) i własny korpus: 1158 dokumentów z 11 domen, m.in. gov.pl, CERT Polska i Sejm. Ocenę fact-checkera tego samego twierdzenia kod przekłada na naszą skalę. Gdy strona blokuje nasz serwer, bierzemy fragment z wyników wyszukiwarki; blokad nie obchodzimy. Model wskazuje cytaty, a kod sprawdza je słowo w słowo w źródle i wyznacza werdykt według reguł.

Przy źródle widać tytuł, wydawcę, datę publikacji, link i dosłowny cytat, jeśli go mamy. Strona WWW, /czat i Discord podpisują ocenę fact-checkera i fragment z wyszukiwarki, a strona podaje też datę pobrania. Stare materiały oznaczamy jako archiwalne. Na /zrodla są źródła z licencjami i odrzucone, z powodem.

Wzorce w kodzie i flaga modelu wyłapują polecenia ukryte w tekście, na stronie z linku i w źródłach. Traktujemy je jak dane i zapisujemy zdarzenie bezpieczeństwa. PESEL, numery dowodu i paszportu, telefon, e-mail, numery kont i kart maskujemy przed modelem i logami. Każde sprawdzenie zostawia zamaskowany wpis w dzienniku (pytanie, źródła, wynik, czasy, koszt) na 30 dni; na stronie i w /czat można go usunąć. Zamaskowane logi kontenerów są poza retencją i usuwaniem.

Kanały to strona WWW i adapter demonstracyjny komunikatora pod /czat, oba na tym samym API. Kod bota Discord (/sprawdz) czeka na wdrożenie. Serwer stoi w Niemczech (OVHcloud). Poza EOG trafia zamaskowany tekst do Anthropic i zapytania do wyszukiwarki (Perplexity albo Tavily), a Google, EUvsDisinfo i gov.pl nie podają, gdzie przetwarzają dane. Model każdego kroku ustawia zmienna środowiskowa.

Pełny przebieg naszego testu (commit a14b93c, 75 przypadków, lokalne API, evals/results/HISTORY.md): macro-F1 0,92 przy celu 0,75 (69 przypadków z oceną; 42 etykiety to oceny Demagoga, które produkt może przejąć), pokrycie cytatami 1,0, poprawność cytatów 1,0 (tylko obecność cytatu z korpusu w źródle, nie wsparcie twierdzenia), poprawna abstencja 1,0 (12), odporność na wstrzyknięcia w tekście 1,0 (7, 3 z nich nasze wzorce znają dosłownie), mediana czasu 20,5 s, zgodność kanałów 1,0 (6, drugi kanał dostał wynik z pamięci podręcznej), pętla moderatora 1,0 (2), end-to-end 0,99. Koszt modeli: 3,45 USD za 100 sprawdzeń, bez opłat za wyszukiwarkę. 11 przypadków z poleceniem ukrytym na pobranej stronie przeszło osobno na commicie 5e5be00: 11 z 11 trafnych ocen, odporność 1,0. Razem 73 z 80 trafnych ocen, macro-F1 0,92 (dwa przebiegi, docs/eval-notes.md).

End-to-end nie przeszedł J01: przy symulowanej awarii Fact Check produkt dał ocenę zamiast komunikatu technicznego. Spośród 7 pomyłek w ocenie 4 to „brak wystarczających dowodów” zamiast oceny. Baza incydentów jest pusta (brak pliku organizatora), 259 dokumentów korpusu nie ma daty, a fact-checkerów reprezentuje w nim 15 tekstów Pravdy. Nie obsługujemy zrzutów ekranu i nie maskujemy imion ani adresów.

## Przed wysłaniem (nie wklejać do formularza)

Do formularza idzie tylko tekst spod „Opis do formularza”, do tego nagłówka: 3869 znaków
(`len()`, znaki nowej linii jako LF), 3883 z CRLF; limit 4000 znaków
([issue #18](https://github.com/00200200/HackNation2026/issues/18)). Liczby z pełnego przebiegu:
[evals/results/history/20261122T061635.151613Z-a14b93c-full.json](../../evals/results/history/20261122T061635.151613Z-a14b93c-full.json);
przypadki E05-E15:
[20261122T075024.922599Z-5e5be00-full.json](../../evals/results/history/20261122T075024.922599Z-5e5be00-full.json)
i [20261122T075409.798208Z-5e5be00-full.json](../../evals/results/history/20261122T075409.798208Z-5e5be00-full.json);
jak je łączymy, 42 etykiety z ocen Demagoga, pamięć podręczna drugiego kanału i trzy przypadki
wstrzyknięć znane wzorcom: [eval-notes.md](../eval-notes.md). Szczegóły:
[architektura](architecture.md), [źródła](sources.md), [ryzyka](risks.md), [koszty](cost.md),
[prywatność](../privacy.md), [korpus](../corpus.md).

- Wkleić tekst do formularza i sprawdzić jego licznik.
- Upublicznić repozytorium albo podać inny link (22.11 o 9:30 było prywatne).
- Gdy bot Discord będzie na serwerze dostępnym dla jury, poprawić zdanie o nim w akapicie o
  kanałach i dodać link zaproszenia.
