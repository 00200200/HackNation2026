# Czego faktczyfejk nie obsługuje

Opis zadania wymaga, żeby zespół ujawnił przypadki, których system nie obsługuje (sekcja 6). Ta lista mówi,
co system robi w każdym z nich i co wtedy widzi użytkownik. Komunikaty są przepisane z kodu słowo w słowo.
Stan na 22.11.2026, gałąź `main`, commit `1aa173f`. Numery `#n` to otwarte zadania w
[repozytorium](https://github.com/00200200/HackNation2026/issues).

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
| Długa strona i budżet czasu 25 s | W pomiarze na żywo z 21.11 wszystkie twierdzenia z długiej strony gov.pl dostały `nie sprawdzono` ([#63](https://github.com/00200200/HackNation2026/issues/63)). | "Nie sprawdzono: skończył się czas przeznaczony na sprawdzenie (25 s). Spróbuj sprawdzić to twierdzenie osobno." | `pipeline.py` |

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
| Więcej twierdzeń niż limit jednego sprawdzenia | Pięć najważniejszych według modelu sprawdza w pełni (`PRAWDOWID_MAX_CHECKED_CLAIMS`, domyślnie 5). Resztę wypisuje bez oceny. | Sekcja "Niesprawdzone twierdzenia": "Jedno sprawdzenie obejmuje tylko najważniejsze twierdzenia z tekstu. Tych nie oceniliśmy. Możesz wkleić je osobno." i lista zdań. |
| Tekst bez twierdzenia do sprawdzenia, za krótki albo zbyt niejasny | `needs_clarification`. | "Nie znaleźliśmy w tym tekście żadnego twierdzenia. Napisz pełnym zdaniem, co chcesz sprawdzić." |
| Tekst dłuższy niż 5000 znaków | Strona nie wysyła wejścia, API też je odrzuca (422). | "Treść jest za długa. Limit to 5000 znaków." |
| Puste pole | Strona nie wysyła wejścia, API też je odrzuca (422). | "Wpisz tekst do sprawdzenia." |
| Dane osobowe w tekście | Zastępuje e-mail, numer konta (NRB i IBAN), numer karty, PESEL oraz telefon w formacie `+48 600 100 200` lub `600-100-200` znacznikiem przed wysłaniem do modelu. Twierdzenia o samym numerze nie sprawdzi. Nie maskuje imion i nazwisk, adresów, telefonów zapisanych jako `600 100 200` ani numerów dowodów i paszportów ([#82](https://github.com/00200200/HackNation2026/issues/82)). | Bez komunikatu. W twierdzeniu widać znacznik: `[e-mail]`, `[numer konta]`, `[numer karty]`, `[PESEL]` lub `[telefon]`. |
| Link razem z innym tekstem, kilka linków naraz | Traktuje wejście jak zwykły tekst i nie pobiera stron. | Zwykła odpowiedź, bez komunikatu. |

## Awarie i limity

| Przypadek | Co robi system | Komunikat dla użytkownika |
|---|---|---|
| Więcej niż 10 sprawdzeń na minutę z jednego adresu IP | Odpowiada kodem 429. Bot Discord liczy wszystkich swoich użytkowników jako jeden adres. | Tytuł "Nie możemy przyjąć tego zapytania" i zdanie "Wysłano za dużo zapytań w krótkim czasie. Odczekaj minutę i spróbuj ponownie." |
| Model nie odpowiada albo brakuje klucza | `technical_error`. | "Nie udało się przeprowadzić sprawdzenia, bo model językowy nie odpowiedział. Spróbuj ponownie za chwilę." |
| Wyodrębnianie twierdzeń przekracza budżet czasu | `technical_error`. | "Sprawdzenie trwało za długo, więc je przerwaliśmy. Spróbuj ponownie albo wklej krótszy tekst." |
| Model odmawia analizy | `cannot_check`. | "Model językowy odmówił analizy tego tekstu, więc nie możemy go sprawdzić." |
| Inny wyjątek w API | `technical_error`. | "Wystąpił błąd techniczny i nie udało się sprawdzić tej treści. Spróbuj ponownie za chwilę." Gdy strona w ogóle nie dostaje odpowiedzi: "Nie udało się połączyć z usługą. Spróbuj ponownie za chwilę." |
| Dla twierdzenia zawiodły wszystkie źródła albo skończył się czas | Ocena `nie sprawdzono`. To nie jest werdykt. | W "Czego nie ustaliliśmy": "Nie sprawdzono: żadne źródło nie zwróciło wyników ani nie odpowiedziało, więc nie wydajemy werdyktu." albo "Nie sprawdzono: skończył się czas przeznaczony na sprawdzenie (25 s). Spróbuj sprawdzić to twierdzenie osobno." Nad tym: "Nie sprawdziliśmy tego twierdzenia." i "To nie jest ocena: źródła nie odpowiedziały albo zabrakło czasu." |
| Część źródeł nie działa, a pozostałe nic nie znalazły | Błąd ([#60](https://github.com/00200200/HackNation2026/issues/60)): twierdzenie dostaje ocenę `brak wystarczających dowodów`, a awarie wymienia tylko wśród ograniczeń. Czytelnik może odebrać to jako brak dowodów na świecie. | "Nie udało mi się potwierdzić tej informacji." i w "Czego nie ustaliliśmy" na przykład "Wyszukiwanie w bazie Google Fact Check było niedostępne, więc nie sprawdziliśmy, czy ktoś już zweryfikował to twierdzenie." albo "Wyszukiwarka internetowa nie odpowiedziała albo nie zwróciła wyników, więc nie szukaliśmy źródeł w sieci." |

Źródła komunikatów: [`prawdowid/app.py`](../prawdowid/app.py), [`prawdowid/verifier.py`](../prawdowid/verifier.py),
[`prawdowid/pipeline.py`](../prawdowid/pipeline.py), [`frontend/public/app.js`](../frontend/public/app.js).

## Czego nie ma w ogóle

- Pętla informacji. Nie ma kolejki spraw moderatora, grupowania powtórzonych pytań ani powiadomień. Pytanie bez
  źródeł sprawdzamy od nowa za każdym razem i nigdy nie piszemy, że sprawę przekazano
  ([#79](https://github.com/00200200/HackNation2026/issues/79)).
- Baza incydentów organizatora. Dopasowanie działa, ale baza jest pusta, więc notatka "Podobne znane incydenty"
  nie pojawia się ([#64](https://github.com/00200200/HackNation2026/issues/64)).
- Ostrzeżenie o statusie źródła, na przykład objęciu sankcjami UE
  ([#81](https://github.com/00200200/HackNation2026/issues/81)).
- Własny korpus w sprawdzeniu. `corpus/evidence.jsonl` istnieje, ale `verify()` go nie przeszukuje
  ([#74](https://github.com/00200200/HackNation2026/issues/74)).
- Drugi kanał na serwerze demo. Bot Discord jest w kodzie, ale nie działa na `faktczyfejk.pl` i nie ma zaproszenia
  dla jury ([#59](https://github.com/00200200/HackNation2026/issues/59)).
- Usuwanie sprawdzeń z Discorda. Nie ma polecenia usunięcia, a odpowiedzi bota widać w kanale, w którym go użyto.
