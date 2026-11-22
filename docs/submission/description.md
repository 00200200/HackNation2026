# Opis zgłoszenia

Nazwa zespołu: TEAM_NAME

Tytuł: faktczyfejk.pl: sprawdź, zanim podasz dalej

## Opis do formularza

<!-- description:start -->
faktczyfejk.pl sprawdza twierdzenia z wklejonego tekstu albo ze strony pod linkiem. Działa na https://faktczyfejk.pl, za darmo i bez konta. Odpowiada po polsku: przy każdym twierdzeniu podaje ocenę, uzasadnienie, ograniczenia i źródła.

Projektowaliśmy go dla dwóch grup. Pierwsza to osoba, która dostała wiadomość na czacie i chce ją sprawdzić, zanim prześle ją dalej, nawet jeśli słabo radzi sobie z technologią. Druga to analityk lub moderator w MSZ, któremu potrzebny jest ślad: jakie źródła sprawdziliśmy i skąd wzięła się ocena. Badań z użytkownikami nie prowadziliśmy.

Claude Opus (przez PydanticAI) dzieli tekst na twierdzenia, a opinie oznacza jako niepodlegające weryfikacji. Trzy najważniejsze twierdzenia sprawdzamy w pełni, resztę wymieniamy jako niesprawdzoną. Dla każdego równolegle pytamy Google Fact Check Tools (oceny fact-checkerów, także Demagoga), wyszukiwarkę www.gov.pl, wyszukiwarkę Tavily zawężoną do domen wybranych przez zespół oraz EUvsDisinfo, które daje tylko kontekst. Przeszukujemy też własny korpus: 1158 dokumentów z 11 domen (7, jeśli liczyć *.gov.pl jako jedną), m.in. gov.pl, CERT Polska, Policji, Sejmu, IMGW i GUS. Claude Haiku porządkuje znalezione fragmenty, a Claude Sonnet wskazuje w nich cytaty. Kod sprawdza, czy cytat naprawdę jest w źródle, i wyznacza werdykt według reguł.

Ocen jest pięć: potwierdzone, fałszywe, wprowadzające w błąd, brak wystarczających dowodów i nie podlega weryfikacji. Gdy zawiedzie źródło lub model albo skończy się czas, a zebrane dowody nie wystarczają, twierdzenie dostaje „nie sprawdzono”, nie ocenę. Osobno pokazujemy też błąd techniczny, stronę, której nie możemy sprawdzić (paywall, logowanie, media społecznościowe), i prośbę o doprecyzowanie. Przy źródle widać tytuł, wydawcę, datę publikacji i pobrania, link oraz, gdy się da, dosłowny cytat. Stare materiały oznaczamy jako archiwalne, a strona z linku nie jest dowodem dla samej siebie.

Wzorce w kodzie i flaga modelu wyłapują polecenia ukryte w tekście, na stronie z linku i w pobranych źródłach. Traktujemy je jak dane i zapisujemy zdarzenie bezpieczeństwa. PESEL, numer dowodu i paszportu, telefon, e-mail oraz numery kont i kart maskujemy, zanim tekst trafi do modelu i do logów. Każde sprawdzenie zostawia jeden zamaskowany wpis w dzienniku: pytanie, czas, źródła, wynik, czasy kroków i koszt. Wpis przechowujemy 30 dni, a na stronie użytkownik może sam usunąć swoje sprawdzenia. Zamaskowane logi kontenerów nie podlegają tej retencji ani usuwaniu.

Kanał WWW działa. Bot Discord z komendą /sprawdz korzysta z tego samego API, ale nie działa jeszcze na serwerze: brakuje tokenu i serwera testowego. Na wypadek, gdyby nie ruszył, przygotowujemy adapter demonstracyjny w stylu komunikatora, również na tym API.

Serwer stoi w Niemczech (OVHcloud). Poza EOG trafia zamaskowany tekst do modelu (Anthropic) i zapytania do wyszukiwarki (Tavily). Google i EUvsDisinfo nie podają, gdzie przetwarzają dane. Model każdego kroku można zmienić zmienną środowiskową, bez przebudowy.

Ostatni pomiar to szybki test na 10 przypadkach, commit edd34a5 (evals/results/latest.json, 22.11.2026): macro-F1 0,28 przy celu 0,75, pokrycie cytatami 1,0, poprawna abstencja 1,0, odporność na wstrzyknięcia 1,0 (jeden przypadek), mediana czasu 24,9 s, scenariusze end-to-end 0,9, zgodność kanałów 1,0 (klient API bota, bez prawdziwego Discorda), pętla moderatora 0. Poprawności cytatów nie zmierzyliśmy. Koszt modelu: 4,91 USD za 100 sprawdzeń, bez opłat za wyszukiwarkę. Następny krok to pełny test na wszystkich 77 przypadkach.

Najsłabsza jest trafność ocen: w 8 z 10 przypadków szybkiego testu odpowiedź brzmiała „brak wystarczających dowodów”. Baza incydentów organizatora jest pusta, bo nie mamy jeszcze pliku. W korpusie 259 dokumentów nie ma daty publikacji, a fact-checkerów reprezentuje tylko 15 tekstów Pravdy. Nie obsługujemy zrzutów ekranu ani pętli moderatora i nie maskujemy imion ani adresów.
<!-- description:end -->

Liczba znaków opisu: 3921 (ze spacjami i znakami nowej linii, bez znaczników, tytułu, nazwy
zespołu i tej adnotacji). Limit formularza: 4000 znaków
([issue #18](https://github.com/00200200/HackNation2026/issues/18)).

Stan opisu: gałąź `integration/r2` (2e0f8ce), wyniki z
[evals/results/latest.json](../../evals/results/latest.json) (szybki test na edd34a5, opis
przebiegów w [HISTORY.md](../../evals/results/HISTORY.md)). Przed wysłaniem:

- wpisać nazwę zespołu w miejsce TEAM_NAME;
- sprawdzić, czy https://faktczyfejk.pl działa już na tym kodzie (`prod` może być starszy);
- po pełnym teście (#16) podmienić akapit z wynikami;
- gdy bot Discord (#73) albo adapter demonstracyjny (#116) zadziała na serwerze, zmienić akapit
  o kanałach i dopisać, jak jury do nich trafi.

Podstawa opisu: [architektura](architecture.md), [źródła](sources.md), [ryzyka](risks.md),
[koszty](cost.md), [prywatność](../privacy.md), [korpus](../corpus.md).
Stan integracji i testów: [WORKLOG](../../WORKLOG.md). Film pozostaje pracą zespołu.
