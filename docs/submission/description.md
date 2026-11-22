# Opis zgłoszenia

Nazwa zespołu: TEAM_NAME

Tytuł: faktczyfejk.pl: sprawdź, zanim podasz dalej

## Opis do formularza

faktczyfejk.pl sprawdza wiadomość, zanim prześlesz ją dalej. Na https://faktczyfejk.pl wklejasz tekst albo link, bez konta i za darmo, i dostajesz po polsku ocenę twierdzeń z uzasadnieniem, ograniczeniami i źródłami. Myśleliśmy o osobie słabo znającej technologię i o analityku MSZ, który musi wiedzieć, skąd wzięła się ocena.

Ocen jest pięć: potwierdzone, fałszywe, wprowadzające w błąd, brak wystarczających dowodów i nie podlega weryfikacji. Osobno pokazujemy „nie sprawdzono”, błąd techniczny, stronę, której nie da się sprawdzić (paywall, logowanie, media społecznościowe), i prośbę o doprecyzowanie. Awarii nie podajemy jako werdyktu. Gdy nie odpowie model lub źródło zdolne rozstrzygnąć (Fact Check, wyszukiwarka, w sprawach rządu gov.pl) albo minie czas, a innych dowodów brakuje, twierdzenie dostaje „nie sprawdzono” z powodem. Gdy awaria dotknie wszystkich twierdzeń, widać komunikat techniczny.

Claude dzieli tekst na twierdzenia, a trzy najważniejsze sprawdzamy w pełni. Dla każdego równolegle przeszukujemy Google Fact Check Tools (kilka krótkich zapytań: twierdzenie, nazwy, cytaty), Tavily na wybranych domenach, EUvsDisinfo (tylko kontekst), w sprawach rządu www.gov.pl i własny korpus: 1158 dokumentów z 11 domen, m.in. gov.pl, CERT Polska, Policja i Sejm. Ocenę fact-checkera tego samego twierdzenia kod przekłada na naszą skalę i pokazuje jako „Ocena fact-checkera: …”. Gdy strona z listy blokuje nasz serwer, pokazujemy fragment z wyników wyszukiwarki, oznaczony tak i z powodem; blokady nie obchodzimy. Model wskazuje cytaty, a kod sprawdza je słowo w słowo w źródle i wyznacza werdykt według reguł.

Przy źródle widać tytuł, wydawcę, datę publikacji i pobrania, link oraz dosłowny cytat, jeśli go mamy. Stare materiały oznaczamy jako archiwalne. Strona /zrodla wymienia wszystkie źródła z licencjami oraz źródła odrzucone, z powodem.

Wzorce w kodzie i flaga modelu wyłapują polecenia ukryte w tekście, na stronie z linku i w źródłach. Traktujemy je jak dane i zapisujemy zdarzenie bezpieczeństwa. PESEL, numer dowodu i paszportu, telefon, e-mail oraz numery kont i kart maskujemy, zanim tekst trafi do modelu i do logów. Każde sprawdzenie zostawia zamaskowany wpis w dzienniku (pytanie, czas, źródła, wynik, czasy kroków, koszt) na 30 dni, a użytkownik może usunąć swoje wpisy. Logi kontenerów są poza tą retencją.

Kanały to strona WWW i adapter demonstracyjny komunikatora pod /czat, oba na tym samym API. Kod bota Discord (/sprawdz) jest gotowy, wdrożenie czeka. Serwer stoi w Niemczech (OVHcloud), a poza EOG trafia zamaskowany tekst do Anthropic i zapytania do Tavily. Model w każdym kroku wybiera się zmienną środowiskową.

Wyniki: commit ca48b84, pełny przebieg, 75 przypadków (22.11). Macro-F1 0,80 (cel 0,75), pokrycie cytatami 1,0, poprawność cytatów 1,0 (13 cytatów z korpusu, sprawdzonych dosłownie), poprawna abstencja 0,92 (12), odporność na wstrzyknięcia 1,0 (7, wszystkie we wklejonym tekście), mediana czasu 17,8 s, zgodność kanałów 1,0 (6, strona i klient API bota), end-to-end 0,97. Progi jury spełniamy poza end-to-end i pętlą moderatora. Koszt modeli: 4,27 USD za 100 sprawdzeń, bez opłat za wyszukiwarkę. 11 przypadków z poleceniem ukrytym na stronie pominęliśmy (brak publicznego adresu).

Dwie sprawy są otwarte. W J01 (symulowana awaria Fact Check) produkt ocenił twierdzenia z innych źródeł i dopisał, że Fact Check nie działał, a przypadek wymaga komunikatu o awarii; regułę jeszcze ustalamy. Pętlę moderatora (scenariusz H) dopiero budujemy, stąd wynik 0. Na 15 chybionych przypadków 5 to „wprowadzające w błąd” zamiast „fałszywe”. Baza incydentów jest pusta (nie mamy pliku organizatora), 259 dokumentów korpusu nie ma daty, a fact-checkerów reprezentuje w nim 15 tekstów Pravdy. Nie obsługujemy zrzutów ekranu i nie maskujemy imion ani adresów.
