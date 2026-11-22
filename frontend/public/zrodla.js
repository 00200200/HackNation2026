// Source list (/zrodla): renders GET /api/sources. Every row comes from the API, which reads the
// catalogue, the corpus and the search code; nothing about a source is written here.
const lead = document.getElementById("lead");
const REPO = "https://github.com/00200200/HackNation2026/blob/main/";
const STORAGE = { full_text: "pełny tekst", excerpt: "fragment do 500\u00a0znaków i link", none: "nic" };
const WAITING = { candidate: "kandydat do korpusu", live_only: "planowane zapytanie na żywo, bez zapisu" };

// Full text is cut at the catalogue's max_chars (or the corpus default); say where.
function storage(entry) {
  const label = STORAGE[entry.storage] ?? entry.storage;
  return entry.max_chars ? `${label} do ${count(entry.max_chars)}\u00a0znaków` : label;
}

// A table wider than the screen scrolls sideways inside its frame; only then is the frame a named,
// focusable region the keyboard can scroll. Both boxes are watched: the table grows when the font loads.
const overflow = new ResizeObserver((entries) => entries.forEach(({ target }) => {
  const wrap = target.closest(".table-wrap");
  if (wrap.scrollWidth > wrap.clientWidth) {
    wrap.tabIndex = 0;
    wrap.setAttribute("role", "region");
    wrap.setAttribute("aria-labelledby", wrap.dataset.label);
  } else {
    ["tabindex", "role", "aria-labelledby"].forEach((name) => wrap.removeAttribute(name));
  }
}));

// The browser jumps to #anchor before the tables arrive; jump again after them unless the reader moved.
let moved = false;
["wheel", "touchmove", "keydown", "pointerdown"].forEach((type) =>
  addEventListener(type, () => { moved = true; }, { once: true, passive: true }));

function count(n) {
  return n.toLocaleString("pl-PL");
}

function typeLabel(type) {
  return type ? SOURCE_TYPES[type] ?? type : "zależnie od domeny";
}

// The interval after which a (manual) rebuild fetches a source's lists again: "24h" -> "po 24 godzinach".
function interval(value) {
  const match = /^(\d+)([hd])$/.exec(value ?? "");
  if (!match) return "–";
  const n = Number(match[1]);
  if (match[2] === "h") return n === 1 ? "po godzinie" : `po ${n}\u00a0godzinach`;
  return n === 1 ? "po dniu" : `po ${n}\u00a0dniach`;
}

function named(name, detail) {
  return [el("span", { className: "name", textContent: name }), el("span", { className: "sub", translate: false, textContent: detail })];
}

// Catalogue notes and reasons are written in English; marked so screen readers switch language.
function english(text) {
  return text ? el("span", { lang: "en", textContent: text }) : "–";
}

function external(href, text, context) {
  return el("a", { href, rel: "noopener noreferrer", target: "_blank" }, text,
    el("span", { className: "sr-only", textContent: `: ${context} (otwiera się w nowej karcie)` }));
}

// columns: [{ label, num, wide, short }]; rows: one array of cell contents per row, the first cell heads the row.
function table(labelledBy, columns, rows) {
  if (!rows.length) return el("p", { className: "empty", textContent: "Brak pozycji na tej liście." });
  const kind = (column) => {
    const name = ["num", "wide", "short"].find((k) => column[k]);
    return name ? { className: name } : {};
  };
  const head = el("tr", {}, ...columns.map((c) => el("th", { scope: "col", ...kind(c) }, c.label)));
  const body = rows.map(([first, ...rest]) => el("tr", {},
    el("th", { scope: "row" }, ...[first].flat()),
    ...rest.map((content, i) => el("td", kind(columns[i + 1]), ...[content].flat()))));
  const grid = el("table", {}, el("thead", {}, head), el("tbody", {}, ...body));
  grid.setAttribute("aria-labelledby", labelledBy);
  const wrap = el("div", { className: "table-wrap" }, grid);
  wrap.dataset.label = labelledBy;
  overflow.observe(wrap);
  overflow.observe(grid);
  return wrap;
}

function fill(id, node) {
  document.getElementById(id).replaceChildren(node);
}

function status(lookup) {
  if (lookup.active) return el("span", { className: "on", textContent: "włączony" });
  return lookup.needs_key ? "wyłączony, brak klucza API" : "wyłączony";
}

function licence(entry) {
  const terms = safeUrl(entry.licence_url);
  return [
    entry.licence ?? "do potwierdzenia",
    terms ? [" (", external(terms, "warunki", entry.publisher), ")"] : null,
    entry.licence_checked ? el("span", { className: "sub", textContent: `sprawdzone ${plDate(entry.licence_checked)}` }) : null,
  ].flat().filter(Boolean);
}

function records(entry) {
  if (entry.records || !entry.needs_key) return count(entry.records);
  return [count(0), el("span", { className: "sub", textContent: "czeka na klucz API" })];
}

function leadText(data) {
  const { lookups, corpus } = data;
  const on = lookups.filter((l) => l.active).length;
  const live = `Przy każdym sprawdzeniu pytamy na żywo ${plural(lookups.length, "serwis", "serwisy", "serwisów")}`
    + (on === lookups.length ? "." : ` (w tej wersji włączone: ${on}).`);
  const stored = ` Korpus dowodów liczy ${plural(corpus.records, "rekord", "rekordy", "rekordów")}`
    + ` i obejmuje ${plural(corpus.domains, "domenę", "domeny", "domen")}`
    + (corpus.in_checks ? "." : ", ale w tej wersji sprawdzanie go jeszcze nie przeszukuje.");
  const fetched = corpus.last_retrieved_at ? ` Ostatnie pobranie: ${plDate(corpus.last_retrieved_at)}.` : "";
  return live + stored + fetched;
}

function render(data) {
  const { lookups, web_search: domains, corpus, catalogue } = data;
  lead.textContent = leadText(data);
  document.getElementById("govpl-note").hidden = !lookups.some((l) => l.id === "govpl" && l.active);
  document.getElementById("web-licence-note").textContent = domains.some((d) => d.licence)
    ? " Tekst stron archiwizujemy tylko dla domen z licencją wpisaną w kodzie wyszukiwarki (kolumna „Licencja w wyszukiwarce”)."
    : " W kodzie wyszukiwarki żadna domena nie ma wpisanej licencji (wpis obejmuje całą domenę z subdomenami), dlatego tekstu znalezionych stron "
      + "nie archiwizujemy: używamy go tylko w bieżącym sprawdzeniu, a w odpowiedzi cytujemy krótki fragment z linkiem.";

  fill("lookups", table("na-zywo",
    [{ label: "Serwis" }, { label: "Co przeszukuje", wide: true }, { label: "Typ" }, { label: "W tej wersji" }],
    lookups.map((l) => [named(l.name, l.host), l.description, typeLabel(l.source_type), status(l)])));

  fill("web-search", table("domeny",
    [{ label: "Domena" }, { label: "Wydawca", wide: true }, { label: "Typ" }, { label: "Licencja w wyszukiwarce" }],
    domains.map((d) => [el("span", { translate: false, textContent: d.domain }), d.publisher ?? "podany na stronie", typeLabel(d.source_type), d.licence ?? "niewpisana"])));

  document.getElementById("corpus-lead").textContent = "Korpus to dokumenty, które pobraliśmy wcześniej z serwisów urzędowych i fact-checkingowych, "
    + "każdy z datą pobrania. " + (corpus.in_checks
      ? "Przeszukujemy go przy każdym sprawdzeniu, razem z serwisami pytanymi na żywo."
      : "W tej wersji sprawdzanie jeszcze go nie przeszukuje, więc odpowiedzi opierają się tylko na serwisach pytanych na żywo.");
  const types = Object.entries(corpus.source_types).map(([t, n]) => `${typeLabel(t)} ${count(n)}`).join(", ");
  const dated = corpus.records - corpus.without_published_at;
  document.getElementById("corpus-count").textContent = `Datę publikacji ma ${count(dated)} z ${count(corpus.records)} rekordów; `
    + "pozostałym jej nie przypisaliśmy, bo strona jej nie podaje albo jeszcze jej nie odczytujemy. "
    + `Rekordy według typu: ${types}. `
    + "Domeny liczymy według Public Suffix List, w której gov.pl jest sufiksem, więc www.gov.pl i sejm.gov.pl to dwie domeny. "
    + `Gdyby wszystkie adresy *.gov.pl liczyć jako jedną domenę, byłoby ich ${corpus.strict_domains}. `
    + "Korpus przebudowujemy ręcznie, a kolumna „Ponowne pobranie” mówi, po jakim czasie przebudowa pobiera listę źródła na nowo.";

  const active = catalogue.filter((e) => e.status === "active");
  fill("corpus", table("korpus",
    [{ label: "Źródło" }, { label: "Typ" }, { label: "Licencja", wide: true }, { label: "Zapisujemy" },
      { label: "Ponowne pobranie", short: true }, { label: "Rekordy", num: true }, { label: "Ostatnie pobranie", short: true }],
    active.map((e) => [named(e.publisher, e.domain), typeLabel(e.source_type), licence(e), storage(e),
      interval(e.update_interval), records(e), plDate(e.last_retrieved_at) ?? "–"])));

  const waiting = catalogue.filter((e) => e.status === "candidate" || e.status === "live_only");
  fill("candidates", table("kandydaci",
    [{ label: "Źródło" }, { label: "Typ" }, { label: "Status" }, { label: "Licencja", wide: true }, { label: "Czego brakuje", wide: true }],
    waiting.map((e) => [named(e.publisher, e.domain), typeLabel(e.source_type), WAITING[e.status], licence(e), english(e.note)])));

  const excluded = catalogue.filter((e) => e.status === "excluded");
  fill("excluded", table("wykluczone",
    [{ label: "Źródło" }, { label: "Typ" }, { label: "Powód", wide: true }, { label: "Od", short: true }, { label: "W wyszukiwarce" }],
    excluded.map((e) => [named(e.publisher, e.domain), typeLabel(e.source_type), english(e.excluded_reason),
      plDate(e.excluded_on) ?? "–", e.in_web_search ? "tak" : "nie"])));
}

function failed() {
  lead.classList.add("failed");
  lead.replaceChildren("Nie udało się wczytać listy źródeł. Odśwież stronę za chwilę. W repozytorium znajdziesz katalog korpusu (",
    el("a", { href: `${REPO}corpus/catalog.yaml`, textContent: "corpus/catalog.yaml" }), ") i domeny wyszukiwarki (",
    el("a", { href: `${REPO}docs/sources.md`, textContent: "docs/sources.md" }), ").");
}

function refocusAnchor() {
  const target = !moved && location.hash && document.getElementById(location.hash.slice(1));
  if (target) target.scrollIntoView();
}

lead.textContent = "Wczytujemy listę źródeł…";

fetch("/api/sources", { signal: AbortSignal.timeout(15000) })
  .then((resp) => (resp.ok ? resp.json() : Promise.reject(new Error(String(resp.status)))))
  .then(render)
  .then(refocusAnchor, failed);
