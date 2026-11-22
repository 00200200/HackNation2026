# Pitch na etap II i scenariusz filmu

Dwa teksty do mówienia: pitch na żywo (5 minut, potem 5 minut pytań) zbudowany wokół
https://faktczyfejk.pl oraz film demonstracyjny do 3 minut. Odpowiedzi na pytania jury są w
[qa.md](qa.md), plan pilotażu w [pilot.md](pilot.md), koszty w [cost.md](cost.md).

Zasada dla obu tekstów: pokazujemy tylko prawdziwe odpowiedzi z działającej usługi. Liczby bierzemy z
[evals/results/HISTORY.md](../../evals/results/HISTORY.md). Miejsca oznaczone „[z #16]” wypełniamy
po pełnym evalu na commicie zgłoszenia i nie wpisujemy tam niczego wcześniej.

## Część 1. Pitch na żywo, 5 minut

### Przed wejściem na scenę

- Godzinę przed występem jedno sprawdzenie na https://faktczyfejk.pl. Potwierdza, że działają
  klucze, kredyty Tavily i budżet modelu (#75).
- Otwarte karty: strona główna, Discord z komendą `/sprawdz` (jeśli bot działa na produkcji, #59),
  [HISTORY.md](../../evals/results/HISTORY.md), slajd z pilotażem ([pilot.md](pilot.md)).
- Plan awaryjny: film z części 2 i zrzut [docs/readme/answer.png](../readme/answer.png). Jeśli strona
  nie odpowie, mówimy dlaczego i przełączamy się na film. Nie udajemy, że to na żywo.
- Na ekranie nie pokazujemy danych osobowych. Nie wpisujemy też niczego, czego nie sprawdziliśmy
  wcześniej, poza pytaniem od jury.

### Scenariusz

| Czas | Na ekranie | Mówimy |
|---|---|---|
| 0:00-0:30 | Slajd 1 | „Na rodzinnym czacie ktoś wkleja wiadomość. Zanim ktokolwiek ją sprawdzi, idzie dalej. Fact-checki istnieją, ale trzeba wiedzieć, gdzie ich szukać. Chatbot odpowie płynnie, tylko że płynna odpowiedź to jeszcze nie dowód. Dlatego zrobiliśmy faktczyfejk.pl.” |
| 0:30-0:55 | Strona główna | „Wklejasz tekst albo link. Dostajesz odpowiedź po polsku, twierdzenie po twierdzeniu: cytat, wydawca, data i link. Model tylko czyta. Werdykt wylicza kod i tylko z tych cytatów, które naprawdę znaleźliśmy w źródle. A kiedy dowodów nie ma, piszemy wprost, że nie udało się tego potwierdzić.” |
| 0:55-1:50 | Przycisk „Darmowe przejazdy 65+ we Wrocławiu” | Podczas czekania: „Właśnie pytamy równolegle Google Fact Check, EUvsDisinfo, wyszukiwarkę gov.pl i wyszukiwarkę ograniczoną do zaufanych domen. Każde źródło ma własny limit czasu.” Po odpowiedzi czytamy jej pierwsze słowa i pokazujemy źródło z cytatem i datą: „To pytanie pochodzi z przykładów organizatora.” |
| 1:50-2:25 | Przycisk „Pytanie z ukrytym poleceniem” | „To samo pytanie, tylko z dopisanym poleceniem dla modelu. Odpowiedź się nie zmienia. Strona mówi, że w treści były polecenia i że ich nie wykonaliśmy. Każdą taką próbę zapisujemy jako zdarzenie bezpieczeństwa, bez jej treści.” |
| 2:25-2:55 | Przycisk „Bilety tylko w aplikacji” | „Plotka z małej miejscowości, której nikt nie opisał. Tu najłatwiej o zmyślenie. A my mówimy: nie udało się potwierdzić, i wypisujemy, czego brakuje.” |
| 2:55-3:15 | Discord, `/sprawdz` z pytaniem o Wrocław | „Drugi kanał. Ta sama usługa, ten sam werdykt, te same źródła, bo bot nie ma własnej logiki.” Jeśli bot nie działa na produkcji (#59), mówimy to jednym zdaniem i idziemy dalej. |
| 3:15-3:45 | HISTORY.md albo slajd z wynikami | „Testujemy się tak jak jury: 73 przypadki, scenariusze od A do J, te same metryki. Każdy przebieg zapisujemy w repozytorium razem z commitem, także słaby. Pełny przebieg na commicie zgłoszenia: [z #16]. Najsłabsze miejsce: [z #16].” |
| 3:45-4:30 | Slajd z pilotażem | „Jak to wdrożyć w MSZ? Brief podaje pięć etapów i do każdego mamy już kawałek: uruchomienie jednym poleceniem z testami, zamknięty korpus 1158 dokumentów, w tym 1143 urzędowych, maskowanie danych z 30-dniową retencją, wersję publiczną na serwerze w Niemczech i bramkę regresji przed każdą zmianą. Brakuje kolejki eksperta, procedury korekt i zewnętrznego red teamu. Proponujemy start od pytań o bezpieczeństwo podróży na danych z Odyseusza. Każdą odpowiedź do publikacji zatwierdza tam człowiek.” |
| 4:30-5:00 | Slajd 11 | „Nie budujemy sędziego prawdy. Pokazujemy źródło i to, czego nie wiemy, a ostatnie słowo ma czytelnik. Obywatel płaci zero złotych. Fakt ma przypis. Możecie wpisać własne pytanie na żywo, chętnie je sprawdzimy.” |

Suma: 300 s. Jeśli odpowiedź na pierwsze pytanie przyjdzie szybciej, oszczędzony czas zostawiamy na
pytania jury, nie dokładamy demo.

### Czego nie mówimy, a o co mogą zapytać

Nie twierdzimy, że coś działa, jeśli nie działa. Jeśli padnie pytanie, odpowiadamy wprost:

- Trafność werdyktów (macro-F1) w zapisanych przebiegach jest poniżej progu 0,75 z briefu. Wynik na
  commicie zgłoszenia: [z #16].
- Nie ma kolejki moderatora ani eksperta (#79), zrzutów ekranu i zdjęć (scenariusz F, #80) ani
  ostrzeżenia o sankcjach UE (#81).
- Baza incydentów organizatora jest wpięta, ale pusta, bo nie mamy pliku (#64).
- Wyszukiwanie w korpusie nie jest podpięte do sprawdzania (#74).
- Bot Discord działa w kodzie. Jego stan na produkcji: #59.
- Modele i wyszukiwarka to dostawcy spoza EOG, a miejsce przetwarzania danych jest UNCONFIRMED (#85).

## Część 2. Film demonstracyjny, do 3 minut

### Zasady nagrania

- Nagrywamy tylko prawdziwe odpowiedzi. Każde wejście sprawdzamy na żywo najwyżej godzinę przed
  nagraniem. Jeśli wynik różni się od napisu poniżej, zmieniamy napis na to, co faktycznie widać,
  albo wycinamy scenę i mówimy o tym w napisie końcowym.
- Czekanie na odpowiedź można przyciąć, ale wtedy na ekranie pojawia się napis „odpowiedź po N s”
  z prawdziwym czasem.
- Próba i nagranie to około 20 sprawdzeń. Według [cost.md](cost.md) to około 100 kredytów Tavily i
  około 1 USD za modele. Przed nagraniem sprawdzamy stan kredytów (#75).
- Scenę J nagrywamy lokalnie: `make up` bez kluczy w `.env`, strona na http://localhost:8080
  ([README](../../README.md#run)).
- Bez danych osobowych na ekranie. Serwer Discord testowy, bez prywatnych nazw. Ekran 1920×1080,
  powiększenie przeglądarki 125%, napisy wtopione w obraz.
- Link do filmu musi działać bez logowania (brief, część 4).

### Kolejność i napisy

Kolejność: najpierw pytanie organizatora w dwóch kanałach, potem uczciwe „nie wiem”, odporność na
polecenia, pełna skala ocen, kontekst bez werdyktu i na końcu awaria.

| Nr | Czas | Scenariusz | Wejście | Napis na ekranie | Lektor |
|---|---|---|---|---|---|
| 1 | 0:00-0:08 | Wstęp | plansza z logo | „faktczyfejk.pl. Sprawdź, zanim podasz dalej.” | „Dostałeś wiadomość i nie wiesz, czy to prawda? Wklej ją tutaj.” |
| 2 | 0:08-0:38 | G, strona | przycisk „Darmowe przejazdy 65+ we Wrocławiu” (pytanie z przykładów organizatora) | „Źródło, cytat, data. Werdykt liczy kod, nie model.” | „Pytanie z przykładów organizatora. Pod odpowiedzią widać źródło, cytat i datę publikacji.” |
| 3 | 0:38-0:53 | G, Discord | `/sprawdz` z tym samym pytaniem | „Discord: ten sam werdykt, te same źródła.” | „To samo pytanie na Discordzie. Ta sama usługa, ta sama odpowiedź.” |
| 4 | 0:53-1:08 | D | przycisk „Bilety tylko w aplikacji” | „Nie ma źródeł, więc nie zgadujemy.” | „Plotka, której nikt nie opisał. Zamiast zgadywać, piszemy: nie udało się potwierdzić.” |
| 5 | 1:08-1:28 | E | przycisk „Pytanie z ukrytym poleceniem” | „Polecenie w treści pominięte i zapisane jako zdarzenie bezpieczeństwa.” | „Ktoś dopisał polecenie dla modelu. Nie wykonujemy go i mówimy o tym wprost.” |
| 6 | 1:28-1:40 | A | przycisk „Polska w NATO od 1999” | „Prosty fakt, źródło urzędowe.” | „Prosty fakt i od razu źródło.” |
| 7 | 1:40-2:00 | B | przypadek B02 z [evals/cases.jsonl](../../evals/cases.jsonl): „Czy na krążącym nagraniu Greta Thunberg wyśmiewa protesty klimatyczne w Niemczech?” | „Prawdziwe nagranie, zły kontekst: wprowadza w błąd.” | „Nagranie jest prawdziwe, ale pokazane bez kontekstu. Taka odpowiedź mówi, czego brakuje.” |
| 8 | 2:00-2:20 | C | przypadek C02: „Poseł napisał, że 63 miasta znów mają dostęp do kolei, a w komentarzach ktoś twierdzi, że chodzi o przystanki. Czy te 63 miasta to prawda?” | „Sprzeczne wersje: pokazujemy, co mówią źródła.” | „Polityk podaje jedną wersję, komentujący drugą. Odpowiedź pokazuje, co mówią źródła. Gdy dwa wiarygodne źródła sobie przeczą, pokazujemy konflikt zamiast wybierać.” |
| 9 | 2:20-2:35 | I | przypadek I04: „Czy to prawda, że w Buczy nie ginęli cywile?” | „Znana narracja: EUvsDisinfo daje kontekst, nigdy werdykt.” | „Znana narracja dezinformacyjna. Dopasowanie do niej to kontekst. Werdykt i tak wynika ze źródeł.” |
| 10 | 2:35-2:50 | J | localhost bez kluczy, pytanie o NATO | „Brak klucza: komunikat techniczny zamiast werdyktu.” | „A gdy padnie usługa albo zabraknie klucza, mówimy, co się stało. Nie wymyślamy wyniku.” |
| 11 | 2:50-3:00 | Koniec | plansza | „Fakt ma przypis. faktczyfejk.pl · github.com/00200200/HackNation2026” | „Fakt ma przypis. Sprawdź sam na faktczyfejk.pl.” |

Napisy dla scen 7 i 9 to oczekiwane wyniki według etykiet w [evals/cases.jsonl](../../evals/cases.jsonl),
a napis sceny 8 opisuje regułę, nie wynik. Jeśli na próbie wyjdzie inaczej, wpisujemy to, co widać.
Czego się spodziewać:

- Scena 3 wymaga bota na produkcji albo na serwerze testowym (#59). Bez działającego bota wycinamy
  ją i dopisujemy w napisie końcowym: „Discord: uruchomienie w toku, #59”.
- Sceny 7 i 8 zależą od tego, czy wyszukiwarka dotrze do strony fact-checkera. Część z nich blokuje
  nasz serwer (#95). Wtedy odpowiedź może brzmieć „Nie udało mi się potwierdzić tej informacji.” i
  taką pokazujemy, z napisem „źródło zablokowało pobranie, #95”.
- W scenie 9 baza incydentów organizatora jest pusta (#64), więc notatka „Podobne znane incydenty”
  się nie pojawi. Kontekst może przyjść tylko z EUvsDisinfo. Jeśli nie przyjdzie, zostaje sam werdykt
  ze źródeł, a napis brzmi: „Bazy incydentów organizatora jeszcze nie mamy, #64”.

Napis końcowy, jeśli którąś scenę wycięliśmy: „Nie pokazujemy: [scena], bo [powód, numer zgłoszenia].”
