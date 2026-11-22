# Opis zgłoszenia

Nazwa zespołu: Genwrownik

Tytuł: faktczyfejk.pl: sprawdź, zanim podasz dalej

## Opis do formularza

Na https://faktczyfejk.pl wklejasz tekst albo link, bez konta i za darmo, i dostajesz po polsku ocenę twierdzeń z uzasadnieniem, ograniczeniami i źródłami. Myśleliśmy o osobie słabo znającej technologię i o analityku MSZ, który musi wiedzieć, skąd wzięła się ocena.

Ocen jest pięć: potwierdzone, fałszywe, wprowadzające w błąd, brak wystarczających dowodów i nie podlega weryfikacji. Osobno, nigdy jako ocenę, pokazujemy „nie sprawdzono”, błąd techniczny, stronę, której nie da się sprawdzić (paywall, logowanie), i prośbę o doprecyzowanie. „Nie sprawdzono” z powodem dostaje twierdzenie, gdy nie odpowie model, czas minie przed oceną albo padnie źródło zdolne rozstrzygnąć (Fact Check, wyszukiwarka, w sprawach rządu gov.pl), a innych dowodów brak. Awaria przy wszystkich twierdzeniach daje komunikat techniczny.

Claude dzieli tekst na twierdzenia, a trzy najważniejsze sprawdzamy w pełni. Dla każdego równolegle przeszukujemy Google Fact Check Tools, wyszukiwanie w sieci (Perplexity, a bez jego klucza Tavily) na wybranych domenach, www.gov.pl, EUvsDisinfo (tylko kontekst) i własny korpus: 1158 dokumentów z 11 domen, m.in. gov.pl, CERT Polska i Sejm. Ocenę fact-checkera tego samego twierdzenia kod przekłada na naszą skalę. Gdy strona blokuje nasz serwer, bierzemy fragment z wyników wyszukiwarki; blokad nie obchodzimy. Model wskazuje cytaty, a kod sprawdza je słowo w słowo w źródle i wyznacza werdykt według reguł.

Przy źródle widać tytuł, wydawcę, datę publikacji, link i dosłowny cytat, jeśli go mamy. Strona WWW, /czat i Discord podpisują ocenę fact-checkera i fragment z wyszukiwarki, a strona podaje też datę pobrania. Stare materiały oznaczamy jako archiwalne. Na /zrodla są źródła z licencjami i odrzucone, z powodem.

Wzorce w kodzie i flaga modelu wyłapują polecenia ukryte w tekście, na stronie z linku i w źródłach. Traktujemy je jak dane i zapisujemy zdarzenie bezpieczeństwa. PESEL, numery dowodu i paszportu, telefon, e-mail, numery kont i kart maskujemy przed modelem i logami. Każde sprawdzenie zostawia zamaskowany wpis w dzienniku (pytanie, źródła, wynik, czasy, koszt) na 30 dni; na stronie i w /czat można go usunąć.

Kanały to strona WWW i adapter demonstracyjny komunikatora pod /czat, oba na tym samym API. Przygotowaliśmy też bota Discord (/sprawdz). Serwer stoi w Niemczech (OVHcloud). Poza EOG trafia zamaskowany tekst do Anthropic i zapytania do wyszukiwarki (Perplexity albo Tavily). Model każdego kroku ustawia zmienna środowiskowa.

Pełny przebieg naszego testu (75 przypadków): macro-F1 0,92 przy celu 0,75, pokrycie cytatami 1,0, cytaty zgodne słowo w słowo ze źródłem 1,0, poprawna abstencja 1,0 (12), odporność na wstrzyknięcia w tekście 1,0 (7), mediana czasu 20,5 s, zgodność kanałów 1,0 (6), pętla moderatora 1,0 (2), end-to-end 0,99. Koszt 1000 sprawdzeń: 34,47 USD za modele, z Tavily szacunkowo 73,47 USD. W osobnym teście 11 z 11 stron z ukrytym poleceniem dostało trafną ocenę, odporność 1,0. Razem 73 z 80 trafnych ocen.

## Przed wysłaniem (nie wklejać do formularza)

Do formularza idzie tylko tekst spod „Opis do formularza”, do tego nagłówka: 2975 znaków
(`len()`, znaki nowej linii jako LF), 2987 z CRLF; limit 4000 znaków
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
- Film demonstracyjny: https://drive.google.com/file/d/1x0WUqsnHMpuB5Rxm7yWyokUI8V8JJIM5/view?usp=sharing
  (22.11 o 10:15 otwierał się bez logowania; na stronie projektu na hacktribe jest w polu na dodatkowe
  materiały, bo pole filmu przyjmuje tylko YouTube). Prezentacja: `docs/pitch/faktczyfejk-pitch.pdf`.
- Upublicznić repozytorium albo podać inny link (22.11 o 9:30 było prywatne).
- Gdy bot Discord będzie na serwerze dostępnym dla jury, poprawić zdanie o nim w akapicie o
  kanałach i dodać link zaproszenia.
