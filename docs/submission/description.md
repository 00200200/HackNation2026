# Opis zgłoszenia

Nazwa zespołu: TEAM_NAME

Tytuł: faktczyfejk.pl: sprawdź, zanim podasz dalej

## Opis do formularza

<!-- description:start -->
faktczyfejk.pl sprawdza twierdzenia z wklejonego tekstu albo ze strony pod linkiem. Działa na https://faktczyfejk.pl, za darmo i bez konta. Odpowiada po polsku: przy każdym twierdzeniu podaje ocenę, uzasadnienie, ograniczenia i znalezione źródła.

Projektowaliśmy go dla dwóch grup. Pierwsza to osoba, która dostała wiadomość na czacie i chce ją sprawdzić, zanim prześle ją dalej, nawet jeśli słabo radzi sobie z technologią. Druga to analityk lub moderator w MSZ, któremu potrzebny jest ślad: jakie źródła sprawdziliśmy i skąd wzięła się ocena. Badań z użytkownikami nie prowadziliśmy.

Claude (przez PydanticAI) dzieli tekst na twierdzenia, a opinie oznacza jako niepodlegające weryfikacji. Trzy najważniejsze twierdzenia sprawdzamy w pełni, resztę wymieniamy jako niesprawdzoną. Dla każdego równolegle pytamy Google Fact Check Tools (oceny fact-checkerów, także Demagoga), wyszukiwarkę www.gov.pl, wyszukiwarkę Tavily zawężoną do domen wybranych przez zespół oraz EUvsDisinfo, które daje tylko kontekst. Przeszukujemy też własny korpus: 1158 dokumentów z 11 domen (7, jeśli liczyć *.gov.pl jako jedną), m.in. gov.pl, CERT Polska, Policji, Sejmu, IMGW i GUS. Claude Haiku porządkuje znalezione fragmenty, a Claude Sonnet wskazuje w nich cytaty. Kod sprawdza, czy cytat naprawdę jest w źródle, i wyznacza werdykt według reguł.

Ocen jest pięć: potwierdzone, fałszywe, wprowadzające w błąd, brak wystarczających dowodów i nie podlega weryfikacji. Gdy dowodów jest za mało, a nie odpowiedział model oceniający lub źródło zdolne rozstrzygnąć (Fact Check, wyszukiwarka, przy sprawach rządu gov.pl) albo czas minął przed ich odpowiedzią, twierdzenie dostaje „nie sprawdzono” zamiast oceny. Osobno pokazujemy błąd techniczny, stronę, której nie możemy sprawdzić (paywall, logowanie, media społecznościowe), i prośbę o doprecyzowanie. Przy źródle widać tytuł, wydawcę, datę publikacji i pobrania, link oraz, gdy się da, dosłowny cytat. Stare materiały oznaczamy jako archiwalne, a strona z linku nie jest dowodem dla samej siebie.

Wzorce w kodzie i flaga modelu wyłapują polecenia ukryte w tekście, na stronie z linku i w pobranych źródłach. Traktujemy je jak dane i zapisujemy zdarzenie bezpieczeństwa. PESEL, numer dowodu i paszportu, telefon, e-mail oraz numery kont i kart maskujemy, zanim tekst trafi do modelu i do logów. Każde sprawdzenie zostawia zamaskowany wpis w dzienniku: pytanie, czas, źródła, wynik, czasy kroków i koszt. Wpis przechowujemy 30 dni, a na stronie użytkownik może sam usunąć swoje sprawdzenia. Zamaskowane logi kontenerów nie podlegają tej retencji ani usuwaniu.

Kanał WWW działa. Bot Discord z komendą /sprawdz korzysta z tego samego API, ale nie działa jeszcze na serwerze: brakuje tokenu i serwera testowego. Przygotowujemy też adapter demonstracyjny w stylu komunikatora na tym API.

Serwer stoi w Niemczech (OVHcloud). Poza EOG trafia zamaskowany tekst do modelu (Anthropic) i zapytania do wyszukiwarki (Tavily). Google i EUvsDisinfo nie podają, gdzie przetwarzają dane. Model każdego kroku wybiera się zmienną środowiskową (PydanticAI).

Ostatni pomiar: szybki test na 10 przypadkach, commit edd34a5, ekstrakcja Claude Opus (evals/results/latest.json, 22.11.2026). Macro-F1 0,28 przy celu 0,75, pokrycie cytatami 1,0 (tylko oceny merytoryczne), poprawna abstencja 1,0 (2 przypadki), odporność na wstrzyknięcia 1,0 (1 przypadek), mediana czasu 24,9 s, end-to-end 0,9, zgodność kanałów 1,0 (1 przypadek, klient API bota, bez Discorda). Poprawności cytatów nie mierzyliśmy. Koszt modelu: 4,91 USD za 100 sprawdzeń (ok. 49 USD za 1000), bez opłat za wyszukiwarkę.

Najsłabsza jest trafność ocen: w 8 z 10 przypadków szybkiego testu odpowiedź brzmiała „brak wystarczających dowodów”. Baza incydentów organizatora jest pusta: nie mamy jeszcze pliku. W korpusie 259 dokumentów nie ma daty publikacji, a fact-checkerów reprezentuje tylko 15 tekstów Pravdy. Nie obsługujemy zrzutów ekranu ani pętli moderatora i nie maskujemy imion ani adresów.
<!-- description:end -->

Liczba znaków opisu: 3966 (ze spacjami i znakami nowej linii, bez znaczników, tytułu, nazwy
zespołu i tej adnotacji), 3982, jeśli formularz liczy koniec linii jako dwa znaki. Limit
formularza: 4000 znaków ([issue #18](https://github.com/00200200/HackNation2026/issues/18)).
W bajtach UTF-8 tekst ma 4135, więc licznik bajtów by go odrzucił.

Stan opisu: gałąź `integration/r2` (2e0f8ce), wyniki z
[evals/results/latest.json](../../evals/results/latest.json) (szybki test na edd34a5, ekstrakcja
twierdzeń przez Claude Opus, opis przebiegów w [HISTORY.md](../../evals/results/HISTORY.md)).
Tekst nie podaje domyślnego modelu ekstrakcji ani liczby przypadków pełnego testu, bo
`integration/r3` je zmienia (Sonnet od #88, 86 przypadków zamiast 77). Przed wysłaniem:

- wpisać nazwę zespołu w miejsce TEAM_NAME;
- wkleić tekst do formularza i sprawdzić jego licznik;
- sprawdzić, czy https://faktczyfejk.pl działa już na tym kodzie (`prod` może być starszy);
- upublicznić repozytorium albo podać inny link: 22.11.2026 było prywatne, a prowadzą do niego
  slajd 12 oraz nagłówek i stopka strony, a zadanie wymaga linku do repozytorium;
- scalić [PR #124](https://github.com/00200200/HackNation2026/pull/124) albo zmienić zdanie o
  danych poza EOG: źródła do niego są tylko w tabeli dostawców z tego PR, a `docs/privacy.md` na
  tej gałęzi podaje miejsca przetwarzania jako UNCONFIRMED;
- po pełnym teście (#16) podmienić akapit z wynikami i slajd 9;
- gdy bot Discord (#73) albo adapter demonstracyjny (#116) zadziała na serwerze, zmienić akapit
  o kanałach i slajd 8, i dopisać, jak jury do nich trafi.

Podstawa opisu: [architektura](architecture.md), [źródła](sources.md), [ryzyka](risks.md),
[koszty](cost.md), [prywatność](../privacy.md), [korpus](../corpus.md),
[talia slajdów](../pitch/slides.html), miejsca przetwarzania u dostawców:
[PR #124](https://github.com/00200200/HackNation2026/pull/124).
Stan integracji i testów: [WORKLOG](../../WORKLOG.md). Film pozostaje pracą zespołu.
