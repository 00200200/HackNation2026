# Opis zgłoszenia

Nazwa zespołu: TEAM_NAME

Tytuł: faktczyfejk.pl: sprawdź, zanim podasz dalej

## Opis do formularza

Na https://faktczyfejk.pl wklejasz tekst albo link, bez konta i za darmo, i dostajesz po polsku ocenę twierdzeń z uzasadnieniem, ograniczeniami i źródłami. Piszemy dla osoby słabo znającej technologię i analityka MSZ, który musi wiedzieć, skąd wzięła się ocena.

Ocen jest pięć: potwierdzone, fałszywe, wprowadzające w błąd, brak wystarczających dowodów i nie podlega weryfikacji. Osobno, nigdy jako ocenę, pokazujemy „nie sprawdzono” (nie odpowiedział model, minął czas albo padło źródło zdolne rozstrzygnąć, a innych dowodów brak), błąd techniczny, stronę nie do sprawdzenia i prośbę o doprecyzowanie.

Claude dzieli tekst na twierdzenia. Trzy najważniejsze sprawdzamy w jednym przejściu wyszukiwania, równolegle w Google Fact Check Tools, Tavily na wybranych domenach, www.gov.pl, EUvsDisinfo (tylko kontekst) i naszym korpusie (1158 dokumentów z 11 domen). Ocenę fact-checkera tego samego twierdzenia, też ze strony recenzji (ClaimReview) i zdania „…oceniamy jako fałsz”, kod przekłada na naszą skalę. Luka w danych wskazana przez fact-checkera daje „brak wystarczających dowodów”, chyba że stanowisko zajmuje wniosek fact-checkera albo późniejsze wiarygodne źródło. Gdy strona blokuje nasz serwer, bierzemy fragment z wyszukiwarki; blokad nie obchodzimy. Model wskazuje cytaty, kod sprawdza je słowo w słowo w źródle i wyznacza werdykt według reguł.

Przy źródle widać tytuł, wydawcę, datę, link i dosłowny cytat albo podpisaną ocenę fact-checkera, a przy starym materiale ostrzeżenie. Źródła z licencjami są na /zrodla.

Polecenia ukryte w tekście, na stronie z linku i w źródłach wyłapują wzorce w kodzie i flaga modelu; traktujemy je jak dane i zapisujemy zdarzenie bezpieczeństwa. PESEL, numery dowodu i paszportu, telefon, e-mail, numery kont i kart maskujemy przed modelem i logami. Zamaskowany wpis w dzienniku (pytanie, źródła, wynik, czasy, koszt) trzymamy 30 dni; na stronie i w /czat można go usunąć (poza logami kontenerów).

Brak dowodów, zdarzenie bezpieczeństwa albo niepotwierdzone twierdzenie o temacie wysokiego ryzyka otwiera sprawę dla moderatora; podobne pytania łączą się w jedną. Sprawy powstają przy ustawionym PRAWDOWID_ADMIN_TOKEN, z którym moderator czyta je przez GET /api/cases.

Kanały: strona WWW i adapter demonstracyjny komunikatora /czat na tym samym API; bot Discord (/sprawdz) czeka na wdrożenie. Serwer stoi w Niemczech (OVHcloud). Poza EOG trafia zamaskowany tekst do Anthropic i zapytania do Tavily; Google, EUvsDisinfo i gov.pl nie podają, gdzie przetwarzają dane.

Pełny przebieg naszego testu (main, commit c422f2d, 75 przypadków, wyszukiwarka Tavily jak na produkcji): macro-F1 0,92 przy celu 0,75 (42 z 69 etykiet to oceny Demagoga, które produkt może przejąć), pokrycie cytatami 1,0, poprawność cytatów 1,0 (tylko obecność cytatu z korpusu w źródle), abstencja 1,0 (12 z 12), odporność na wstrzyknięcia 1,0 (7 we wklejonym tekście, 3 znane naszym wzorcom), mediana 14,6 s, zgodność kanałów 1,0 (6, drugi kanał z pamięci wyników), pętla moderatora 1,0 (2), end-to-end 0,99. Koszt modeli: 3,46 USD za 100 sprawdzeń, bez wyszukiwarki. Pominęliśmy 11 przypadków z poleceniem na stronie (brak publicznego adresu). Wynik tego samego kodu waha się o kilka punktów, bo modele i wyszukiwarka odpowiadają różnie.

End-to-end nie przeszedł tylko J01 (przy symulowanej awarii Fact Check oceny z innych źródeł z dopiskiem o awarii zamiast komunikatu technicznego). Z 7 pozostałych pomyłek 4 to „brak wystarczających dowodów” zamiast oceny. Baza incydentów jest pusta (brak pliku organizatora), 259 dokumentów korpusu nie ma daty, a fact-checkerów reprezentuje w nim 15 tekstów Pravdy. Nie obsługujemy zrzutów ekranu i nie maskujemy imion ani adresów.

## Przed wysłaniem (nie wklejać do formularza)

Do formularza idzie tylko tekst spod „Opis do formularza”, do tego nagłówka, bez pustych linii na
brzegach: 3687 znaków (`len()`, znaki nowej linii jako LF), 3703 z CRLF i 3874 bajty UTF-8 z CRLF;
limit 4000 znaków ([issue #18](https://github.com/00200200/HackNation2026/issues/18)). Liczby
pochodzą z pełnego przebiegu na `main` przy commicie `c422f2d` (75 przypadków, 2026-11-22T07:21:52Z,
`dirty: false`, staging zbudowany z tego commita, sprawdzony sumą md5 `prawdowid/judge.py` i
`prawdowid/websearch.py`, wyszukiwarka Tavily jak na produkcji):
[evals/results/history/20261122T071235.638303Z-c422f2d-full.json](../../evals/results/history/20261122T071235.638303Z-c422f2d-full.json).
Co stoi za każdą liczbą (42 etykiety z ocen Demagoga, pamięć wyników przy drugim kanale, trzy
przypadki wstrzyknięć znane wzorcom, pomyłki): [eval-notes.md](../eval-notes.md). Próbka 12 cytatów,
którą sprawdził agent: [citation_spotcheck.md](../../evals/results/citation_spotcheck.md). Szczegóły:
[architektura](architecture.md), [źródła](sources.md), [ryzyka](risks.md), [koszty](cost.md),
[prywatność](../privacy.md), [korpus](../corpus.md).

- Wpisać nazwę zespołu w miejsce TEAM_NAME.
- Runda 4 jest na `main` (#129, #134 z uzgodnieniem z #130, #133, #73). Liczby w opisie, na slajdzie 9 i w README
  opisują ten kod (`c422f2d`). Jeśli do zgłoszenia trafi nowszy kod produktu, powtórzyć pełny eval.
- Wyszukiwanie: kod używa Perplexity, gdy ustawiono `PERPLEXITY_API_KEY`, a bez niego Tavily z pamięcią wyników.
  Serwer nie ma klucza Perplexity, więc działa na Tavily, jak mówi opis.
- Wypchnąć `main` na `prod` ([deploy.md](../deploy.md): `prod` bierze tylko commity z `main`).
  22.11 o 04:30 `/czat` i `/zrodla` zwracały na faktczyfejk.pl 404. Gałąź `prod` (`24e92d4`) nie
  ma też między innymi korpusu (#74), ocen fact-checkera ze stron recenzji i ze zdania
  „…oceniamy jako fałsz” (#127, reguły sędziego), podpisanej oceny przy źródle, maskowania numeru
  dowodu i paszportu (#82) ani kolejki moderatora (#79). Bez wdrożenia akapity 3 do 7 opisu i
  slajdy 3, 6, 7, 8 i 10 opisują więc w części kod, którego strona nie ma. Gdy `/czat` zadziała, na
  slajdzie 8 zmienić jego znacznik na „działa” i wyrenderować PDF i PPTX (polecenia w
  `docs/pitch/slides.html`). Jeśli nie zdążymy: w pierwszym akapicie opisu i na slajdzie 8
  napisać, że faktczyfejk.pl działa jeszcze na starszym kodzie, a opis, slajdy i liczby dotyczą
  `main` (`c422f2d`); usunąć z opisu `/czat`, `/zrodla` i akapit o kolejce moderatora, a ze slajdu 3
  zdanie o kolejce; przeliczyć znaki i wyrenderować deck.
- W `.env` serwera produkcyjnego ustawić `PRAWDOWID_ADMIN_TOKEN` (polecenie w
  [deploy.md](../deploy.md)). Bez niego faktczyfejk.pl nie zakłada spraw, więc akapit o kolejce
  moderatora i zdanie o kolejce na slajdzie 3 nie opisują demo.
- Otworzyć kilka stron z [próbki cytatów](../../evals/results/citation_spotcheck.md): sprawdził ją
  agent, nie człowiek.
- Wkleić tekst do formularza i sprawdzić jego licznik.
- Upublicznić repozytorium albo podać inny link (22.11 było prywatne).
- Nagrać film do 3 minut i podać link, który otwiera się bez logowania (scenariusz w
  [pitch.md](pitch.md), część 2).
- Gdy bot Discord (#73) zadziała, poprawić akapit o kanałach i slajd 8.
