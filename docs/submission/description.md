# Opis zgłoszenia

Nazwa zespołu: TEAM_NAME

Tytuł: faktczyfejk.pl: sprawdź, zanim podasz dalej

## Opis do formularza

Na https://faktczyfejk.pl wklejasz tekst albo link, bez konta i za darmo, i dostajesz po polsku ocenę twierdzeń z uzasadnieniem, ograniczeniami i źródłami. Myśleliśmy o osobie słabo znającej technologię i o analityku MSZ, który musi wiedzieć, skąd wzięła się ocena.

Ocen jest pięć: potwierdzone, fałszywe, wprowadzające w błąd, brak wystarczających dowodów i nie podlega weryfikacji. Osobno, nigdy jako ocenę, pokazujemy „nie sprawdzono”, błąd techniczny, stronę, której nie da się sprawdzić (paywall, logowanie), i prośbę o doprecyzowanie. „Nie sprawdzono” z powodem dostaje twierdzenie, gdy nie odpowie model, czas minie przed oceną albo padnie źródło zdolne rozstrzygnąć (Fact Check, wyszukiwarka, w sprawach rządu gov.pl), a innych dowodów brak. Awaria przy wszystkich twierdzeniach daje komunikat techniczny.

Claude dzieli tekst na twierdzenia, a trzy najważniejsze sprawdzamy w pełni. Dla każdego równolegle przeszukujemy Google Fact Check Tools, wyszukiwarkę Tavily na wybranych domenach, www.gov.pl, EUvsDisinfo (tylko kontekst) i własny korpus: 1158 dokumentów z 11 domen, m.in. gov.pl, CERT Polska i Sejm. Ocenę fact-checkera tego samego twierdzenia kod przekłada na naszą skalę. Gdy strona blokuje nasz serwer, bierzemy fragment z wyników wyszukiwarki; blokad nie obchodzimy. Model wskazuje cytaty, a kod sprawdza je słowo w słowo w źródle i wyznacza werdykt według reguł.

Przy źródle widać tytuł, wydawcę, datę publikacji, link i dosłowny cytat, jeśli go mamy. Strona WWW i Discord (jeszcze nie /czat) podpisują ocenę fact-checkera i fragment z wyszukiwarki, a strona podaje też datę pobrania. Stare materiały oznaczamy jako archiwalne. Na /zrodla są źródła z licencjami i odrzucone, z powodem.

Wzorce w kodzie i flaga modelu wyłapują polecenia ukryte w tekście, na stronie z linku i w źródłach. Traktujemy je jak dane i zapisujemy zdarzenie bezpieczeństwa. PESEL, numery dowodu i paszportu, telefon, e-mail, numery kont i kart maskujemy przed modelem i logami. Każde sprawdzenie zostawia zamaskowany wpis w dzienniku (pytanie, źródła, wynik, czasy, koszt) na 30 dni; na stronie i w /czat można go usunąć. Zamaskowane logi kontenerów są poza retencją i usuwaniem.

Kanały to strona WWW i adapter demonstracyjny komunikatora pod /czat, oba na tym samym API. Kod bota Discord (/sprawdz) czeka na wdrożenie. Serwer stoi w Niemczech (OVHcloud). Poza EOG trafia zamaskowany tekst do Anthropic i zapytania do Tavily, a Google, EUvsDisinfo i gov.pl nie podają, gdzie przetwarzają dane. Model każdego kroku ustawia zmienna środowiskowa.

Pełny przebieg naszego testu (commit ca48b84, 75 przypadków, evals/results/HISTORY.md): macro-F1 0,80 przy celu 0,75 (42 etykiety to oceny Demagoga, które produkt może przejąć), pokrycie cytatami 1,0, poprawność cytatów 1,0 (tylko obecność cytatu z korpusu w źródle, nie wsparcie twierdzenia), poprawna abstencja 0,92 (12), odporność na wstrzyknięcia 1,0 (7, we wklejonym tekście, 3 z nich nasze wzorce znają dosłownie), mediana czasu 17,8 s, zgodność kanałów 1,0 (6, drugi kanał dostał wynik z pamięci podręcznej), end-to-end 0,97. Koszt modeli: 4,27 USD za 100 sprawdzeń, bez opłat za wyszukiwarkę. Pominęliśmy 11 przypadków z poleceniem na stronie (brak publicznego adresu).

End-to-end nie przeszły J01 (przy symulowanej awarii Fact Check produkt dał oceny z innych źródeł, z dopiskiem o awarii, zamiast komunikatu technicznego) i A15 (opinia dostała prośbę o doprecyzowanie zamiast „nie podlega weryfikacji”). Pętla moderatora (scenariusz H) weszła do kodu po tym przebiegu (#79), więc tu ma wynik 0. Spośród 15 pomyłek 5 to „wprowadzające w błąd” zamiast „fałszywe”. Baza incydentów jest pusta (brak pliku organizatora), 259 dokumentów korpusu nie ma daty, a fact-checkerów reprezentuje w nim 15 tekstów Pravdy. Nie obsługujemy zrzutów ekranu i nie maskujemy imion ani adresów.

## Przed wysłaniem (nie wklejać do formularza)

Do formularza idzie tylko tekst spod „Opis do formularza”, do tego nagłówka: 3802 znaki
(`len()`, znaki nowej linii jako LF), 3816 z CRLF, 3993 bajty UTF-8 z CRLF; limit 4000 znaków
([issue #18](https://github.com/00200200/HackNation2026/issues/18)). Liczby z pełnego przebiegu:
[evals/results/history/20261122T021757.182695Z-ca48b84-full.json](../../evals/results/history/20261122T021757.182695Z-ca48b84-full.json)
i ostatni wiersz [HISTORY.md](../../evals/results/HISTORY.md); 42 etykiety z ocen Demagoga, pamięć
podręczna drugiego kanału i trzy przypadki wstrzyknięć znane wzorcom:
[eval-notes.md](../eval-notes.md). Szczegóły: [architektura](architecture.md),
[źródła](sources.md), [ryzyka](risks.md), [koszty](cost.md), [prywatność](../privacy.md),
[korpus](../corpus.md).

- Wpisać nazwę zespołu w miejsce TEAM_NAME.
- Sprawdzić, czy https://faktczyfejk.pl działa na kodzie `integration/r3`: 22.11 o 04:30 `/czat`
  i `/zrodla` zwracały 404, a `prod` bierze tylko commity z `main` ([deploy.md](../deploy.md)).
  Od tego zależą też trasa fact-checkera, podpisy fragmentów z wyszukiwarki i maskowanie numeru
  dowodu i paszportu. Gdy `/czat` zadziała, na slajdzie 8 zmienić jego znacznik na „działa” i
  wyrenderować PDF i PPTX (polecenia w `docs/pitch/slides.html`). Jeśli nie zdążymy, usunąć
  `/czat` i `/zrodla` z opisu.
- Wkleić tekst do formularza i sprawdzić jego licznik.
- Upublicznić repozytorium albo podać inny link (22.11 było prywatne).
- Scalić PR #124 (tabela miejsc przetwarzania) albo przeformułować zdanie o EOG.
- Gdy bot Discord (#73) albo podpisy źródeł w `/czat` zadziałają, poprawić akapit o kanałach i
  źródłach oraz slajd 8.
