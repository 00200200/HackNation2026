# Opis zgłoszenia

Nazwa zespołu: TEAM_NAME

Tytuł: faktczyfejk.pl: sprawdź, zanim podasz dalej

## Opis do formularza

Na https://faktczyfejk.pl wklejasz tekst albo link, bez konta i za darmo, i dostajesz po polsku ocenę twierdzeń z uzasadnieniem, ograniczeniami i źródłami. Piszemy dla osoby słabo znającej technologię i analityka MSZ, który musi wiedzieć, skąd wzięła się ocena.

Ocen jest pięć: potwierdzone, fałszywe, wprowadzające w błąd, brak wystarczających dowodów i nie podlega weryfikacji. Osobno, nigdy jako ocenę, pokazujemy „nie sprawdzono” (nie odpowiedział model, minął czas albo padło źródło zdolne rozstrzygnąć, a innych dowodów brak), błąd techniczny, stronę nie do sprawdzenia i prośbę o doprecyzowanie.

Claude dzieli tekst na twierdzenia. Trzy najważniejsze sprawdzamy w jednym przejściu wyszukiwania, równolegle w Google Fact Check Tools, Tavily na wybranych domenach, www.gov.pl, EUvsDisinfo (tylko kontekst) i naszym korpusie (1158 dokumentów z 11 domen). Ocenę fact-checkera tego samego twierdzenia, też ze strony recenzji (ClaimReview) i zdania „…oceniamy jako fałsz”, kod przekłada na naszą skalę. Luka w danych wskazana przez fact-checkera daje „brak wystarczających dowodów”, chyba że stanowisko zajmuje wniosek fact-checkera albo późniejsze wiarygodne źródło. Gdy strona blokuje nasz serwer, bierzemy fragment z wyszukiwarki; blokad nie obchodzimy. Model wskazuje cytaty, kod sprawdza je słowo w słowo w źródle i wyznacza werdykt według reguł.

Przy źródle widać tytuł, wydawcę, datę, link i dosłowny cytat albo podpisaną ocenę fact-checkera, a przy starym materiale ostrzeżenie. Źródła z licencjami są na /zrodla.

Polecenia ukryte w tekście, na stronie z linku i w źródłach wyłapują wzorce w kodzie i flaga modelu; traktujemy je jak dane i zapisujemy zdarzenie bezpieczeństwa. PESEL, numery dowodu i paszportu, telefon, e-mail, numery kont i kart maskujemy przed modelem i logami. Zamaskowany wpis w dzienniku (pytanie, źródła, wynik, czasy, koszt) trzymamy 30 dni; na stronie i w /czat można go usunąć (poza logami kontenerów).

Brak dowodów, zdarzenie bezpieczeństwa albo temat wysokiego ryzyka otwiera sprawę w kolejce moderatora; podobne pytania łączą się w jedną. Kolejka działa przy ustawionym PRAWDOWID_ADMIN_TOKEN, z którym moderator czyta sprawy przez GET /api/cases.

Kanały: strona WWW i adapter demonstracyjny komunikatora /czat na tym samym API; bot Discord (/sprawdz) czeka na wdrożenie. Serwer stoi w Niemczech (OVHcloud). Poza EOG trafia zamaskowany tekst do Anthropic i zapytania do Tavily; Google, EUvsDisinfo i gov.pl nie podają, gdzie przetwarzają dane.

Pełny przebieg naszego testu (commit df74cef, 75 przypadków; w evals/results/HISTORY.md jako f4c9aa8): macro-F1 0,89 przy celu 0,75 (trafnych 62 z 69; 42 etykiety to oceny Demagoga, które produkt może przejąć), pokrycie cytatami 1,0, poprawność cytatów 1,0 (tylko obecność cytatu z korpusu w źródle), abstencja 1,0 (12 z 12), odporność na wstrzyknięcia 1,0 (7 we wklejonym tekście, 3 znane naszym wzorcom), mediana 16,0 s (15,1 s z pustą pamięcią wyszukiwań, af7ec13), zgodność kanałów 1,0 (6, drugi kanał z pamięci wyników), pętla moderatora 1,0 (2), end-to-end 0,97. Koszt modeli: 3,54 USD za 100 sprawdzeń, bez wyszukiwarki. Pominęliśmy 11 przypadków z poleceniem na stronie (brak publicznego adresu). Wynik tego samego kodu waha się o kilka punktów, bo modele i wyszukiwarka odpowiadają różnie.

End-to-end nie przeszły J01 (przy symulowanej awarii Fact Check oceny z innych źródeł z dopiskiem o awarii zamiast komunikatu technicznego) i A15 (przy opinii prośba o doprecyzowanie zamiast „nie podlega weryfikacji”). Z 6 pozostałych pomyłek 4 to „brak wystarczających dowodów” zamiast oceny. Baza incydentów jest pusta (brak pliku organizatora), 259 dokumentów korpusu nie ma daty, a fact-checkerów reprezentuje w nim 15 tekstów Pravdy. Nie obsługujemy zrzutów ekranu i nie maskujemy imion ani adresów.

## Przed wysłaniem (nie wklejać do formularza)

Do formularza idzie tylko tekst spod „Opis do formularza”, do tego nagłówka, bez pustych linii na
brzegach: 3792 znaki (`len()`, znaki nowej linii jako LF), 3808 z CRLF i 3988 bajtów UTF-8 z CRLF;
limit 4000 znaków ([issue #18](https://github.com/00200200/HackNation2026/issues/18)). Liczby
pochodzą z pełnego przebiegu na kodzie `df74cef` (75 przypadków, 2026-11-22T05:40:07Z,
`dirty: false`):
[evals/results/history/20261122T053047.203200Z-f4c9aa8-full.json](../../evals/results/history/20261122T053047.203200Z-f4c9aa8-full.json).
Plik i wiersz w [HISTORY.md](../../evals/results/HISTORY.md) mają znacznik `f4c9aa8`, czyli
`df74cef` z samymi wynikami evalu (`git diff --stat df74cef f4c9aa8` zmienia tylko
`evals/results/`). Kontener stagingu zbudowano z tego kodu i sprawdzono to sumą md5 pliku
`prawdowid/judge.py` (opis commita `fb13425`). Mediana z pustą pamięcią wyszukiwań pochodzi z
przebiegu na `af7ec13`:
[evals/results/history/20261122T043246.052204Z-af7ec13-full.json](../../evals/results/history/20261122T043246.052204Z-af7ec13-full.json).
Co stoi za każdą liczbą (42 etykiety z ocen Demagoga, pamięć wyników przy drugim kanale, trzy
przypadki wstrzyknięć znane wzorcom, pomyłki): [eval-notes.md](../eval-notes.md). Szczegóły:
[architektura](architecture.md), [źródła](sources.md), [ryzyka](risks.md), [koszty](cost.md),
[prywatność](../privacy.md), [korpus](../corpus.md).

- Wpisać nazwę zespołu w miejsce TEAM_NAME.
- Scalić do `main` PR rundy 4 z gałęzi `integration/r4`; zastępuje on PR #126, #123, #124 i #128.
  Na `main` jest już #130 (`379fa8c`, 22.11 06:48), którego `integration/r4` nie zawiera, więc
  scalenie wymaga rozwiązania konfliktów. Liczby w opisie, na slajdzie 9 i w README opisują kod
  `df74cef`: jeśli zgłaszany kod będzie inny, także po takim scaleniu, powtórzyć pełny eval i
  poprawić liczby.
- Wypchnąć `main` na `prod` ([deploy.md](../deploy.md): `prod` bierze tylko commity z `main`).
  22.11 o 04:30 `/czat` i `/zrodla` zwracały na faktczyfejk.pl 404. Od wdrożenia zależą też ocena
  fact-checkera ze strony recenzji, podpisy źródeł, maskowanie numeru dowodu i paszportu oraz
  kolejka moderatora. Gdy `/czat` zadziała, na slajdzie 8 zmienić jego znacznik na „działa” i
  wyrenderować PDF i PPTX (polecenia w `docs/pitch/slides.html`). Jeśli nie zdążymy, usunąć z
  opisu `/czat`, `/zrodla` i akapit o kolejce moderatora.
- W `.env` serwera produkcyjnego ustawić `PRAWDOWID_ADMIN_TOKEN` (polecenie w
  [deploy.md](../deploy.md)). Bez niego faktczyfejk.pl nie zakłada spraw, więc akapit o kolejce
  moderatora nie opisuje demo.
- Wkleić tekst do formularza i sprawdzić jego licznik.
- Upublicznić repozytorium albo podać inny link (22.11 było prywatne).
- Nagrać film do 3 minut i podać link, który otwiera się bez logowania (scenariusz w
  [pitch.md](pitch.md), część 2).
- Gdy bot Discord (#73) zadziała, poprawić akapit o kanałach i slajd 8.
