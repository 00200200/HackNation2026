# Czego faktczyfejk nie obsługuje

Opis zadania wymaga, żeby zespół ujawnił przypadki, których system nie obsługuje (sekcja 6). Ta lista mówi,
co system robi w każdym z nich i co wtedy widzi użytkownik. Komunikaty są przepisane z kodu słowo w słowo.
Stan na 22.11.2026: build demo, czyli gałąź `integration/r4`. `main` (`1aa173f`) jest jej przodkiem i nie ma zmian
z [listy w README](../README.md#zmiany-czekające-na-scalenie). Po nowych commitach w `integration/r4` komunikaty trzeba
sprawdzić ponownie.
Gdzie `main` zachowuje się inaczej, wiersz to mówi. Numery `#n` to zadania w [repozytorium](https://github.com/00200200/HackNation2026/issues).

Gdy system nie może ocenić treści, nie pokazuje werdyktu. Strona wyświetla neutralną informację (bez kolorów
werdyktów) z jednym z trzech tytułów i zdaniem "To nie jest ocena prawdziwości tej treści.":

| Stan w API | Tytuł na stronie |
|---|---|
| `cannot_check` | Nie możemy tego sprawdzić |
| `technical_error` | Nie udało się sprawdzić |
| `needs_clarification` | Doprecyzuj, co chcesz sprawdzić |

Bot Discord pokazuje ten sam komunikat po słowach "Brak oceny.".

## Linki

Linkiem jest wejście z jednym ciągiem znaków zawierającym `://`, bez spacji. Link razem z innym tekstem albo
kilka linków naraz system traktuje jak zwykły tekst: nie pobiera stron i nie mówi o tym nic. Komunikaty
poniżej pochodzą z [`prawdowid/link.py`](../prawdowid/link.py), chyba że napisano inaczej.

| Przypadek | Co robi system | Komunikat dla użytkownika | Kod |
|---|---|---|---|
| Wpis w mediach społecznościowych (lista hostów pod tabelą) | Nie pobiera strony. `cannot_check`. | "Nie pobieramy wpisów z mediów społecznościowych, bo zwykle wymagają logowania. Skopiuj tekst ze strony i wklej go tutaj, a sprawdzimy go." | `SOCIAL_MEDIA` |
| Strona za paywallem albo ze ścianą logowania lub subskrypcji | Adres ze ścieżką `/login`, `/signin`, `/sign-in`, `/logowanie` lub `/zaloguj` odrzuca przed pobraniem. Inne strony rozpoznaje po pobraniu: znacznik schema.org `isAccessibleForFree: false` albo krótki podgląd z prośbą o zalogowanie lub wykupienie dostępu. `cannot_check`. | "Ta strona jest za paywallem lub wymaga logowania. Nie obchodzimy takich zabezpieczeń. Skopiuj tekst ze strony i wklej go tutaj, a sprawdzimy go." | `PAYWALL` |
| Serwer odpowiada kodem 401, 402, 403, 407, 429 lub 451 | `cannot_check`. | "Ta strona nie pozwala na automatyczne pobranie treści. Skopiuj tekst ze strony i wklej go tutaj, a sprawdzimy go." | `BLOCKED` |
| Adres z loginem lub hasłem (`https://uzytkownik:haslo@strona.pl`) | Nie pobiera strony. `cannot_check`. | "Nie pobieramy linków z loginem lub hasłem w adresie. Skopiuj tekst ze strony i wklej go tutaj, a sprawdzimy go." | `CREDENTIALS` |
| Plik inny niż HTML i PDF: obraz, nagranie audio lub wideo, dokument Word lub Excel, zwykły tekst | Decyduje nagłówek `Content-Type` odpowiedzi, nie rozszerzenie pliku. `cannot_check`. | "Pod tym linkiem nie ma strony HTML ani pliku PDF, więc nie możemy go sprawdzić. Skopiuj tekst ze strony i wklej go tutaj, a sprawdzimy go." | `UNSUPPORTED_TYPE` |
| Plik większy niż 2 MB | `cannot_check`. | "Ta strona jest za duża, by ją pobrać (limit 2 MB). Skopiuj tekst ze strony i wklej go tutaj, a sprawdzimy go." | `TOO_LARGE` |
| Strona bez tekstu do odczytania: sama powłoka skryptów, mniej niż 200 znaków tekstu, PDF będący skanem | `cannot_check`. | "Nie udało się wyodrębnić tekstu artykułu z tej strony. Skopiuj tekst ze strony i wklej go tutaj, a sprawdzimy go." | `NO_TEXT` |
| Adres w sieci prywatnej lub lokalnej | Sprawdza adres przy każdym połączeniu, także po przekierowaniu. `cannot_check`. | "Ten adres prowadzi do sieci prywatnej lub lokalnej. Sprawdzamy tylko publiczne strony." | `PRIVATE_ADDRESS` |
| Strony nie ma (inny kod 4xx, na przykład 404) | `cannot_check`. | "Pod tym linkiem nie ma strony (błąd 404). Sprawdź adres albo wklej tekst." Numer błędu zależy od odpowiedzi serwera. | `NOT_FOUND` |
| Więcej niż 3 przekierowania | `cannot_check`. | "Ten link przekierowuje więcej niż 3 razy. Skopiuj tekst ze strony i wklej go tutaj, a sprawdzimy go." | `TOO_MANY_REDIRECTS` |
| Adres z `://` i schematem innym niż `http://` lub `https://` (na przykład `ftp://strona.pl`) | API odrzuca wejście z kodem 422, zanim cokolwiek zostanie sprawdzone. | "To nie wygląda na poprawny link. Przyjmujemy adresy zaczynające się od http:// lub https://." | `app.py` |
| Adres bez schematu (na przykład `onet.pl/artykul`) | Nie jest rozpoznawany jako link, bo linkiem jest tylko jeden ciąg bez spacji, który zawiera `://`. Wejście przechodzi jak zwykły tekst: strona nie jest pobierana i nie ma komunikatu o linku. Co wróci, zależy od modelu, nie mierzyliśmy tego. | Brak osobnego komunikatu. | `verifier.py`, `is_link` |
| Przekierowanie na adres z innym schematem, nieprawidłowy nagłówek `Location` albo protokół, którego nie obsługujemy | `cannot_check`, odpowiedź HTTP 200. | "Przyjmujemy tylko adresy zaczynające się od http:// lub https://." | `link.py`, `BAD_URL` |
| Strona nie odpowiada w 10 s, błąd sieci albo kod 5xx | `technical_error`. | "Nie udało się pobrać tej strony w ciągu 10 s. Spróbuj ponownie za chwilę albo wklej tekst." | `UNREACHABLE` |
| Strona dłuższa niż 5000 znaków (razem z tytułem) | Sprawdza tylko początek. Przy każdym twierdzeniu pojawia się ostrzeżenie. | "Strona jest długa: sprawdziliśmy tylko jej początek (razem z tytułem do 5000 znaków). Resztę tekstu możesz wkleić osobno." | `verifier.py`, `PAGE_CUT` |
| Długa strona i budżet czasu | Całe sprawdzenie ma jeden budżet czasu: 40 s (`PRAWDOWID_CHECK_BUDGET_S`, na `main` 25 s). Twierdzenie, które się nie zmieści, dostaje `nie sprawdzono`. Zgłoszenie [#63](https://github.com/00200200/HackNation2026/issues/63) opisuje obserwację na żywo z 21.11 przy budżecie 25 s, której nie odtworzono w repozytorium: wszystkie twierdzenia z długiej strony gov.pl dostały `nie sprawdzono`. Przypadek U01 (długa strona gov.pl) powstał na tym zgłoszeniu; jego wyniki w kolejnych przebiegach są w [HISTORY.md](../evals/results/HISTORY.md). | "Nie sprawdzono: skończył się czas przeznaczony na sprawdzenie (40 s). Spróbuj sprawdzić to twierdzenie osobno." | `pipeline.py` |

Hosty z listy mediów społecznościowych (z subdomenami): `facebook.com`, `fb.com`, `fb.watch`, `instagram.com`,
`threads.net`, `threads.com`, `x.com`, `twitter.com`, `t.co`, `tiktok.com`, `linkedin.com`, `youtube.com`,
`youtu.be`, `t.me`, `telegram.me`, `vk.com`, `wykop.pl`. To lista stała (`SOCIAL_HOSTS`). Link do serwisu spoza
niej, na przykład Reddita albo Mastodona, jest pobierany jak zwykła strona. Nie sprawdzaliśmy, co z tego wychodzi.

## Tekst i twierdzenia

| Przypadek | Co robi system | Co widzi użytkownik |
|---|---|---|
| Zrzut ekranu, zdjęcie, nagranie audio lub wideo | Nie przyjmuje ich. Formularz ma tylko pole tekstowe, a polecenie Discord `/sprawdz` tylko parametr `tekst`. Nie ma OCR, transkrypcji ani wyszukiwania obrazów ([#80](https://github.com/00200200/HackNation2026/issues/80)). | Strona prosi tylko o tekst albo link ("Wklej tekst albo link…") i nie mówi wprost, że obrazów nie przyjmuje. Osobnego komunikatu nie ma. Link do pliku z obrazem lub nagraniem kończy się komunikatem o pliku innym niż HTML i PDF (tabela wyżej), a link do YouTube'a komunikatem o mediach społecznościowych. |
| Tekst w innym języku niż polski | Nie wykrywa języka. Model dostaje polecenie pracy na polskim tekście, twierdzenia i zapytania pisze po polsku, Google Fact Check pytany jest z `languageCode=pl`, a Tavily z `language="pl"`. Źródeł w innych językach nie szuka ([#89](https://github.com/00200200/HackNation2026/issues/89)). | Zwykła odpowiedź, bez osobnego komunikatu. W zestawie testowym nie ma przypadku w innym języku, więc nie wiemy, co z tego wychodzi. |
| Prognoza, twierdzenie o przyszłości, opinia, ocena, pytanie retoryczne, życzenie | Model oznacza twierdzenie jako niesprawdzalne, a kod nadaje ocenę `nie podlega weryfikacji` bez szukania źródeł. Granicę między faktem a opinią wyznacza model przy wyodrębnianiu twierdzeń (reguła w jego poleceniu), nie kod. | Etykieta "nie podlega weryfikacji" i zdanie "Opinia, prognoza albo pytanie bez faktu do sprawdzenia.". Odpowiedź zaczyna się od "Tego nie da się sprawdzić: to opinia, prognoza albo pytanie bez faktu do sprawdzenia.". Pod spodem: "Brak źródła przy tej ocenie.", siła dowodów "Brak. Nie zbadaliśmy żadnych dowodów." i przesłanka "Nie zbadaliśmy żadnych źródeł ani dowodów.". |
| Więcej twierdzeń niż limit jednego sprawdzenia | Trzy najważniejsze według modelu sprawdza w pełni (`PRAWDOWID_MAX_CHECKED_CLAIMS`, domyślnie 3, na `main` 5). Resztę wypisuje bez oceny. | Sekcja "Niesprawdzone twierdzenia": "Jedno sprawdzenie obejmuje tylko najważniejsze twierdzenia z tekstu. Tych nie oceniliśmy. Możesz wkleić je osobno." i lista zdań. |
| Tekst bez twierdzenia do sprawdzenia, za krótki albo zbyt niejasny | `needs_clarification`. | "Nie znaleźliśmy w tym tekście żadnego twierdzenia. Napisz pełnym zdaniem, co chcesz sprawdzić." |
| Tekst dłuższy niż 5000 znaków | Strona nie wysyła wejścia, API też je odrzuca (422). | "Treść jest za długa. Limit to 5000 znaków." |
| Puste pole | Strona nie wysyła wejścia, API też je odrzuca (422). | "Wpisz tekst do sprawdzenia." |
| Dane osobowe w tekście | Zastępuje e-mail, numer konta (NRB i IBAN), numer karty, PESEL, numer dowodu osobistego, numer paszportu i telefon znacznikiem przed wysłaniem do modelu. Telefon maskuje, gdy ma numer kierunkowy kraju, kreski (`600-100-200`) albo kierunkowy miasta w nawiasach, a bez nich, gdy dziewięć cyfr zaczyna się od prefiksu komórkowego albo stoi po etykiecie typu "tel.". Twierdzenia o samym numerze nie sprawdzi. Nie maskuje imion i nazwisk ani adresów, a także numeru stacjonarnego bez kierunkowego kraju, nawiasów i etykiety oraz numeru dowodu małymi literami (lista dla `main` i zmiany z `integration/r4` w [docs/privacy.md](privacy.md)). Na `main` maskowanie obejmuje tylko telefon w formacie `+48 600 100 200` lub `600-100-200`, bez dowodów i paszportów ([#82](https://github.com/00200200/HackNation2026/issues/82)). W `integration/r4` numer karty zostaje niezamaskowany po etykiecie produktu (EAN, GTIN, UPC, SKU, kod, nr, numer, partii, lot, id), w adresie URL i jako 13 cyfr z poprawną cyfrą kontrolną EAN-13, więc `nr 4111 1111 1111 1111` trafia do modelu bez maski, a `numer karty 4111 1111 1111 1111` i `karta nr 4111 1111 1111 1111` nadal są maskowane (słowo karta, card, visa, mastercard albo maestro tuż przed numerem wygrywa z etykietą produktu). Dziewięć cyfr bez etykiety zostaje, gdy wygląda na kwotę lub identyfikator ([#113](https://github.com/00200200/HackNation2026/issues/113)). | Bez komunikatu. W twierdzeniu widać znacznik: `[e-mail]`, `[numer konta]`, `[numer karty]`, `[PESEL]`, `[numer dowodu]`, `[numer paszportu]` lub `[telefon]`. |
| Link razem z innym tekstem, kilka linków naraz | Traktuje wejście jak zwykły tekst i nie pobiera stron. | Zwykła odpowiedź, bez komunikatu. |

## Awarie i limity

| Przypadek | Co robi system | Komunikat dla użytkownika |
|---|---|---|
| Więcej niż 10 sprawdzeń na minutę z jednego adresu IP | Odpowiada kodem 429. Bot Discord liczy wszystkich swoich użytkowników jako jeden adres. | Tytuł "Nie możemy przyjąć tego zapytania" i zdanie "Wysłano za dużo zapytań w krótkim czasie. Odczekaj minutę i spróbuj ponownie." |
| Model nie odpowiada albo brakuje klucza | `technical_error`. | "Nie udało się przeprowadzić sprawdzenia, bo model językowy nie odpowiedział. Spróbuj ponownie za chwilę." |
| Wyodrębnianie twierdzeń przekracza budżet czasu | `technical_error`. | "Sprawdzenie trwało za długo, więc je przerwaliśmy. Spróbuj ponownie albo wklej krótszy tekst." |
| Model odmawia analizy | `cannot_check`. | "Model językowy odmówił analizy tego tekstu, więc nie możemy go sprawdzić." |
| Inny wyjątek w API | `technical_error`. | "Wystąpił błąd techniczny i nie udało się sprawdzić tej treści. Spróbuj ponownie za chwilę." Gdy strona w ogóle nie dostaje odpowiedzi: "Nie udało się połączyć z usługą. Spróbuj ponownie za chwilę." |
| Zawiodły wszystkie źródła zewnętrzne (Fact Check, EUvsDisinfo, gov.pl i wyszukiwarka internetowa) | `nie sprawdzono`: awaria, nie werdykt. Trafienia z naszego korpusu liczą się tylko wtedy, gdy same rozstrzygają twierdzenie. Na `main` ta sama sytuacja kończy się `nie sprawdzono` z jednym zdaniem w "Czego nie ustaliliśmy": "Nie sprawdzono: żadne źródło nie zwróciło wyników ani nie odpowiedziało, więc nie wydajemy werdyktu." | W "Czego nie ustaliliśmy": "Nie mogę teraz sprawdzić tego twierdzenia: żadne źródło nie odpowiedziało ani nie dało się odczytać. To awaria techniczna, a nie wynik sprawdzenia: nie wydajemy werdyktu." Nad tym: "Nie sprawdziliśmy tego twierdzenia." i "To nie jest ocena: źródła nie odpowiedziały albo zabrakło czasu." W uzasadnieniu: "To nie jest ocena twierdzenia. Nie mogliśmy go teraz sprawdzić (brak odpowiedzi źródeł albo limit czasu), więc nie wiemy, czy jest prawdziwe. Spróbuj ponownie za chwilę." |
| Padło źródło, które mogło rozstrzygnąć (Fact Check, wszystkie zapytania wyszukiwarki internetowej, a przy twierdzeniu o rządzie wyszukiwarka gov.pl), a pozostałe dowody nie wystarczają | `nie sprawdzono`. Twierdzenie nie dostaje oceny `brak wystarczających dowodów`, bo brak odpowiedzi nie znaczy, że nic nie ma ([#60](https://github.com/00200200/HackNation2026/issues/60)). W `integration/r4` Fact Check liczy się jako padły, gdy zawiodło zapytanie z samym twierdzeniem albo wszystkie zapytania ([#100](https://github.com/00200200/HackNation2026/issues/100)); gdy zawiódł tylko krótszy klucz, wynik zostaje, a w ograniczeniach pojawia się zdanie z liczbą nieudanych zapytań. | W "Czego nie ustaliliśmy": "Nie mogę teraz sprawdzić bazy Google Fact Check z powodu błędu dostępu. To awaria techniczna, a nie wynik sprawdzenia: nie wydajemy werdyktu, a brak odpowiedzi nie znaczy, że nic nie znaleziono." Zamiast "bazy Google Fact Check" może stać "wyszukiwarki internetowej" albo "wyszukiwarki portalu www.gov.pl", a gdy padło kilka, nazwy łączy "ani". Pod spodem ograniczenia, na przykład "Wyszukiwanie w bazie Google Fact Check było niedostępne, więc nie sprawdziliśmy, czy ktoś już zweryfikował to twierdzenie." albo "Wyszukiwarka internetowa nie odpowiedziała, więc nie szukaliśmy źródeł w sieci." W `integration/r4` przy częściowej awarii Fact Check: "Część zapytań do bazy Google Fact Check ({failed} z {total}) się nie powiodła, więc mogliśmy nie znaleźć istniejącej weryfikacji tego twierdzenia." Zamiast `{failed}` i `{total}` stoją liczby zapytań nieudanych i wszystkich. |
| Każde sprawdzalne twierdzenie skończyło się awarią źródła albo modelu | Cała odpowiedź to `technical_error`, bez twierdzeń. Na `main` takiej zmiany nie ma: odpowiedź zostaje `ok`, a twierdzenia mają `nie sprawdzono`. | Tytuł "Nie udało się sprawdzić" i komunikat pierwszego twierdzenia, na przykład "Nie mogę teraz sprawdzić bazy Google Fact Check z powodu błędu dostępu. To awaria techniczna, a nie wynik sprawdzenia: nie wydajemy werdyktu, a brak odpowiedzi nie znaczy, że nic nie znaleziono." |
| Model oceniający źródła nie odpowiada | `nie sprawdzono`. Gdy tak jest przy każdym sprawdzalnym twierdzeniu, cała odpowiedź to `technical_error` (na `main` odpowiedź zostaje `ok`). | "Nie udało się ocenić źródeł, bo model językowy nie odpowiedział, więc nie wydajemy werdyktu." |
| Skończył się czas sprawdzenia | `nie sprawdzono`, a odpowiedź zostaje zwykła (`ok`): to limit czasu, nie awaria źródeł. Na `main` w komunikacie stoi 25 s. | "Nie sprawdzono: skończył się czas przeznaczony na sprawdzenie (40 s). Spróbuj sprawdzić to twierdzenie osobno." |
| Źródło odpowiedziało i nic nie znalazło, albo padło tylko źródło, które nie rozstrzyga (EUvsDisinfo, a przy twierdzeniu nie o rządzie gov.pl) | `brak wystarczających dowodów`. Awaria źródła, które nie rozstrzyga, zostaje wśród ograniczeń. Na `main` tak samo kończy się awaria części źródeł, gdy pozostałe nic nie znalazły; `nie sprawdzono` jest tam tylko wtedy, gdy zawiodły wszystkie źródła, skończył się czas albo model oceniający nie odpowiedział ([#60](https://github.com/00200200/HackNation2026/issues/60)). | "Nie udało mi się potwierdzić tej informacji." i w "Czego nie ustaliliśmy" ograniczenia źródeł. |
| Fact-checker sam uznał twierdzenie za nieweryfikowalne albo napisał, że brakuje danych ("nieweryfikowalne"), a żaden fact-checker ani późniejsze wiarygodne źródło nie zajęło stanowiska | `brak wystarczających dowodów` (ADR 0001, sekcja 3). Zdanie werdyktu fact-checkera ("…oceniamy jako fałsz") liczy się natomiast jako jego ocena. | "Nie udało mi się potwierdzić tej informacji." |
| Strona z wyników wyszukiwania blokuje serwer, nie odpowiada na czas, jest za duża albo nie da się jej odczytać ([#95](https://github.com/00200200/HackNation2026/issues/95)) | Blokady nie obchodzi. Zostaje tytuł i fragment z wyników wyszukiwarki, oznaczone jako takie. Strona wyłączona przez robots.txt, nieistniejąca (404, 410), za logowaniem lub płatnością (401, 402) albo przekierowująca poza listę dozwolonych domen jest pomijana. Dowód z samego fragmentu nigdy nie daje siły `silna`, a pojedynczy fragment z wyszukiwarki sam nie potwierdza twierdzenia ([#127](https://github.com/00200200/HackNation2026/issues/127)); wyjątkiem jest zdanie fact-checkera, który sam ocenia twierdzenie. | W "Czego nie ustaliliśmy": "{wydawca}: źródło znamy tylko z fragmentu w wynikach wyszukiwarki, bo strona nie pozwala na pobranie." Zamiast ostatniego członu może stać "strona nie odpowiedziała", "strona nie odpowiedziała na czas", "strona jest za duża do pobrania" albo "nie udało się odczytać treści strony". W przesłance: "fragment z wyników wyszukiwarki". |
| Strona z wyników wyszukiwania bez daty publikacji ([#95](https://github.com/00200200/HackNation2026/issues/95)) | Zostaje, bez daty. Nigdy nie daje siły `silna`. | W "Czego nie ustaliliśmy": "Źródło bez daty publikacji: {wydawca}." |

Źródła komunikatów: [`prawdowid/app.py`](../prawdowid/app.py), [`prawdowid/verifier.py`](../prawdowid/verifier.py),
[`prawdowid/pipeline.py`](../prawdowid/pipeline.py), [`frontend/public/app.js`](../frontend/public/app.js).

## Czego nie ma w ogóle

- Pętla informacji działa tylko częściowo. Kolejka moderatora ([#79](https://github.com/00200200/HackNation2026/issues/79))
  zakłada sprawę, gdy twierdzenie kończy się `brak wystarczających dowodów`, padło zdarzenie bezpieczeństwa albo
  twierdzenie dotyczy tematu wysokiego ryzyka, i łączy podobne pytania w jedną sprawę. Robi to tylko wtedy, gdy ustawiono
  `PRAWDOWID_ADMIN_TOKEN` (czy jest ustawiony na serwerze demo: UNCONFIRMED); bez niego nic nie jest zgłaszane,
  a odpowiedź nie wspomina moderatora. Zdanie "Zgłoszenie trafiło do kolejki moderatora" pojawia się dopiero po
  zapisaniu sprawy. Na `main` kolejki nie ma, a pytanie bez źródeł sprawdzamy tam od nowa za każdym razem. W `integration/r4` gotowa
  odpowiedź na ten sam tekst, także `brak wystarczających dowodów`, wraca z pamięci przez 30 minut
  ([#59](https://github.com/00200200/HackNation2026/issues/59); nagłówek `X-Cache: hit`), a interfejs
  tego nie oznacza ([#121](https://github.com/00200200/HackNation2026/issues/121)). Pamięć jest w procesie, mieści 500 odpowiedzi i po restarcie jest pusta, więc
  ponowne sprawdzenie zaczyna się po wygaśnięciu wpisu, po restarcie albo gdy nowsze odpowiedzi wyprą go z pamięci.
  Odpowiedź z błędem technicznym albo z twierdzeniem `nie sprawdzono` do pamięci nie trafia. Trafienia Tavily dla tego
  samego zapytania mogą wracać z naszej pamięci zapytań, domyślnie do 24 godzin od pierwszego takiego zapytania
  ([#110](https://github.com/00200200/HackNation2026/issues/110)).
- Baza incydentów organizatora. Dopasowanie działa, ale baza jest pusta, więc notatka "Podobne znane incydenty"
  nie pojawia się ([#64](https://github.com/00200200/HackNation2026/issues/64)).
- Ostrzeżenie o statusie źródła, na przykład objęciu sankcjami UE
  ([#81](https://github.com/00200200/HackNation2026/issues/81)).
- Drugi kanał na serwerze demo. Bot Discord jest w kodzie, ale według [#59](https://github.com/00200200/HackNation2026/issues/59) nie działa na `faktczyfejk.pl`
  i nie ma zaproszenia dla jury (tego nie sprawdzaliśmy, [PR #73](https://github.com/00200200/HackNation2026/pull/73)). Strona `/czat`
  ([#116](https://github.com/00200200/HackNation2026/issues/116): adapter demonstracyjny w stylu komunikatora, ten sam `POST /api/checks` z `X-Channel: demo`)
  jest w `integration/r4`, na `main` jej nie ma. Czy jury policzy ją jako drugi kanał, nie sprawdzaliśmy.
- Usuwanie sprawdzeń z Discorda. Nie ma polecenia usunięcia, a odpowiedzi bota widać w kanale, w którym go użyto. Sesję może usunąć tylko operator, wywołaniem API z id z dziennika. Użytkownik Discorda tego id nie zna, a repozytorium nie wskazuje kontaktu do takiej prośby ([docs/privacy.md](privacy.md#demo-session-and-deletion)).
