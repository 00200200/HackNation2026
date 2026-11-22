# Opis zgłoszenia

Nazwa zespołu: TEAM_NAME

Tytuł: Prawdowid: sprawdź twierdzenie i zobacz źródła

## Opis do formularza

<!-- description:start -->
Prawdowid pomaga sprawdzić twierdzenia z tekstu lub strony internetowej. Użytkownik wkleja treść albo link, a usługa wyodrębnia twierdzenia i szuka materiałów, które mogą je potwierdzić lub podważyć. Wynik jest po polsku. Pokazuje ocenę, przesłanki i ograniczenia oraz odnośniki do źródeł z cytatami, jeśli udało się je znaleźć.

Projekt odpowiada na zadanie MSZ dotyczące weryfikacji informacji. Chcemy pomóc osobom, które przed udostępnieniem wiadomości potrzebują sprawdzić jej podstawy. To planowana grupa odbiorców; badania użytkowników nie są potwierdzone w repozytorium.

Formularz WWW i komenda Discord /sprawdz korzystają z tego samego API. Obsługa Discorda jest w kodzie, ale połączenie z prawdziwym serwerem nie zostało potwierdzone testem. Model językowy dzieli tekst na twierdzenia, porządkuje materiały i ocenia znaczenie fragmentów. Ostateczna ocena wynika z reguł w kodzie i cytatów znalezionych w pobranych materiałach. Cytat potwierdza obecność tekstu w źródle; jego poprawna interpretacja nadal może wymagać sprawdzenia przez człowieka.

Źródeł szukamy przez Google Fact Check Tools oraz Perplexity Search API. Wyszukiwanie ograniczamy do domen wybranych przez zespół. EUvsDisinfo przez MCP dostarcza kontekstu znanych narracji dezinformacyjnych, a baza incydentów organizatora pokazuje ewentualne dopasowanie jako neutralną notatkę. Samo podobieństwo do takiej narracji nie rozstrzyga prawdziwości. Własna baza PostgreSQL jest przygotowana, lecz wyłączona z procesu sprawdzania do czasu wyboru materiałów z potwierdzonymi prawami do wykorzystania.

Dane osobowe (e-mail, numer konta, PESEL, telefon) są maskowane przed modelem i w każdym logu. Zapis sprawdzenia trzymamy 30 dni, a użytkownik może usunąć swoją sesję. Brak dowodów i awaria usługi mają osobne komunikaty. Opinie są oznaczane jako niepodlegające weryfikacji, a twierdzenia poza zakresem sprawdzenia są wymieniane jako niesprawdzone. Podany link nie jest dowodem dla własnych twierdzeń.

Prototyp ma istotne braki: baza incydentów organizatora jest jeszcze pusta, nie zbudowaliśmy korpusu demonstracyjnego, a część wymaganych metryk nie została zmierzona. Wyniki, koszty i ryzyka opisujemy w repozytorium. Priorytetem pozostaje budowa korpusu, odporność na polecenia ukryte w treści oraz pełna ochrona danych przed pokazem publicznym.
<!-- description:end -->

Liczba znaków opisu: 2309 (ze spacjami i znakami nowej linii, bez znaczników,
tytułu, nazwy zespołu i tej adnotacji). Limit formularza: 4000 znaków
([issue #18](https://github.com/00200200/HackNation2026/issues/18)).

Podstawa opisu: [architektura i dokładne wyniki testu](architecture.md),
[źródła](sources.md), [ryzyka](risks.md), [koszty](cost.md).
Stan integracji i testów na żywo: [WORKLOG](../../WORKLOG.md).
Nazwa TEAM_NAME wymaga uzupełnienia przez zespół. PDF i film pozostają pracą człowieka.
