// Web channel: send the input to the API and render CheckResult. No verification logic here.
const form = document.getElementById("check-form");
const input = document.getElementById("input");
const submit = document.getElementById("submit");
const formError = document.getElementById("form-error");
const result = document.getElementById("result");
const chips = document.querySelectorAll("[data-example]");

const SECURITY_NOTE = "W treści są zwroty, które wyglądają na polecenia dla modelu. Nie wykonaliśmy ich i sprawdziliśmy resztę.";
const SOURCE_SECURITY_NOTE = "W źródłach są zwroty, które wyglądają na polecenia dla modelu. Nie wykonaliśmy ich i sprawdziliśmy resztę.";
const SECURITY_NOTE_ONLY = "W treści są zwroty, które wyglądają na polecenia dla modelu. Nie wykonaliśmy ich.";
const MAX_CHARS = 5000;
const GENERIC_ERROR = "Nie udało się połączyć z usługą. Spróbuj ponownie za chwilę.";
const NOT_A_VERDICT = "To nie jest ocena prawdziwości tej treści.";
const NOTICE_TITLES = {
  technical_error: "Nie udało się sprawdzić",
  cannot_check: "Nie możemy tego sprawdzić",
  needs_clarification: "Doprecyzuj, co chcesz sprawdzić",
};
const PLURAL = new Intl.PluralRules("pl-PL");
// Values used by the corpus branch and the web-search PR; anything else is shown as sent.
const SOURCE_TYPES = {
  official: "źródło oficjalne",
  fact_checker: "serwis fact-checkingowy",
  fact_check: "serwis fact-checkingowy",
  incident_base: "baza incydentów dezinformacji",
  disinfo_database: "baza znanych narracji dezinformacyjnych",
  news: "serwis informacyjny",
};
// First words of the answer, in the organiser's format ("Tak." / "Nie." / "Nie udało mi się potwierdzić…"),
// picked from the verdict set in code. The reasons stay in the sources and limitations.
const VERDICT_MEANING = {
  confirmed: "Wiarygodne źródła mówią to samo.",
  false: "Wiarygodne źródła mówią coś przeciwnego.",
  misleading: "Fakty się zgadzają, ale bez kontekstu, czasu albo miejsca wprowadzają w błąd.",
  insufficient_evidence: "Za mało źródeł, żeby rozstrzygnąć. Nie zgadujemy.",
  not_verifiable: "Opinia, prognoza albo pytanie bez faktu do sprawdzenia.",
  not_checked: "To nie jest ocena: źródła nie odpowiedziały albo zabrakło czasu.",
};
// A source older than this is flagged as archival, as the brief asks. Same default as the backend's
// ARCHIVE_DAYS in prawdowid/judge.py, which then also lists it under "Czego nie ustaliliśmy".
const ARCHIVAL_DAYS = 730;
const DAY_MS = 24 * 60 * 60 * 1000;
const ANSWER_LEAD = {
  confirmed: "Tak.",
  false: "Nie.",
  misleading: "To wprowadza w błąd.",
  insufficient_evidence: "Nie udało mi się potwierdzić tej informacji.",
  not_verifiable: "Tego nie da się sprawdzić: to opinia, prognoza albo pytanie bez faktu do sprawdzenia.",
  // Not a verdict: the reason follows from the limitations.
  not_checked: "Nie sprawdziliśmy tego twierdzenia.",
};
// Enter sends only with a hardware keyboard; on touch keyboards it adds a new line.
const ENTER_SENDS = window.matchMedia("(hover: hover) and (pointer: fine)");
let busy = false;
let errorFrame = 0;

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  Object.assign(node, attrs);
  node.append(...children.filter((c) => c !== null && c !== undefined && c !== false));
  return node;
}

// The API counts characters, not UTF-16 units: an emoji is one character.
function chars(text) {
  return [...text].length;
}

function plural(n, one, few, many) {
  const form = PLURAL.select(n);
  return `${n} ${form === "one" ? one : form === "few" ? few : many}`;
}

function plDate(value) {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString("pl-PL", { timeZone: "Europe/Warsaw" });
}

function safeUrl(url) {
  return /^https?:\/\//.test(url ?? "") ? url : null;
}

// Anything that is not a verdict: neutral look, never the colours of a verdict.
// No role here: the #result region is already aria-live, a second live role would announce it twice.
function notice(title, text, note) {
  return el("div", { className: "notice" },
    el("strong", { textContent: title }),
    text ? el("span", { textContent: text }) : null,
    note ? el("p", { className: "note", textContent: note }) : null);
}

function sourceItem(s, i) {
  const url = safeUrl(s.url);
  const host = url ? new URL(url).hostname.replace(/^www\./, "") : null;
  const title = url
    ? el("a", { href: url, textContent: `„${s.title}”`, rel: "noopener noreferrer", target: "_blank" })
    : `„${s.title}”`;
  // published_at is a date (YYYY-MM-DD): read the year from the text, so no time zone can shift it.
  const year = s.published_at ? Number(String(s.published_at).slice(0, 4)) : null;
  const age = s.published_at ? (Date.now() - Date.parse(`${s.published_at}T00:00:00Z`)) / DAY_MS : NaN;
  const archival = Boolean(year) && age > ARCHIVAL_DAYS;
  const meta = [
    host,
    s.published_at ? `opublikowano ${plDate(s.published_at)}` : "bez daty publikacji",
    s.fetched_at ? `pobrano ${plDate(s.fetched_at)}` : null,
    SOURCE_TYPES[s.source_type] ?? s.source_type,
  ].filter(Boolean).join(", ");
  return el("li", { className: "source" },
    s.fragment ? el("blockquote", { className: "quote", textContent: `„${s.fragment}”` }) : null,
    el("p", { className: "source-head" }, el("span", { className: "ref", textContent: `[${i + 1}]` }), " ",
      s.publisher ? el("b", { textContent: s.publisher }) : null, s.publisher ? ", " : null, title),
    el("p", { className: "source-meta" },
      archival ? el("span", { className: "archival", textContent: `materiał archiwalny, ${year}` }) : null,
      archival ? " " : null, meta));
}

// Claims from a quote: who said it, and what was said. Plain statements get no tag.
const KIND_LABELS = { attribution: "Kto co powiedział", quoted: "Treść cytatu" };

function origin(c) {
  return el("p", { className: "origin" },
    KIND_LABELS[c.kind] ? el("span", { className: "kind", textContent: KIND_LABELS[c.kind] }) : null,
    `W tekście: ${c.source_sentence}`);
}

function uncheckedList(claims) {
  return el("section", { className: "unchecked" },
    el("h2", { textContent: "Niesprawdzone twierdzenia" }),
    el("p", { textContent: "Jedno sprawdzenie obejmuje tylko najważniejsze twierdzenia z tekstu. "
      + "Tych nie oceniliśmy. Możesz wkleić je osobno." }),
    el("ul", {}, ...claims.map((t) => el("li", { textContent: t }))));
}

function answerText(c) {
  const publishers = [...new Set(c.sources.map((s) => s.publisher).filter(Boolean))];
  const named = publishers.length ? `${publishers.length === 1 ? "Źródło" : "Źródła"}: ${publishers.join(", ")}.` : null;
  return [ANSWER_LEAD[c.verdict] ?? `${c.verdict_label}.`, named].filter(Boolean).join(" ");
}

function claimBlock(c) {
  return el("div", { className: "claim" },
    el("h2", { className: "claim-text", textContent: `„${c.claim}”` }),
    origin(c),
    el("p", { className: "claim-meta" },
      el("span", { className: `verdict verdict-${c.verdict}`, textContent: c.verdict_label }),
      VERDICT_MEANING[c.verdict] ? el("span", { className: "verdict-meaning", textContent: VERDICT_MEANING[c.verdict] }) : null),
    el("p", { className: "answer", textContent: answerText(c) }),
    el("h3", { className: "part", textContent: "Co mówią źródła" }),
    c.sources.length
      ? el("ol", { className: "sources" }, ...c.sources.map(sourceItem))
      : el("p", { className: "empty", textContent: "Brak źródła przy tej ocenie." }),
    el("h3", { className: "part", textContent: "Nasza ocena" }),
    el("div", { className: "assessment" },
      el("p", { className: "explain" }, el("b", { textContent: "Wyjaśnienie modelu: " }), c.reasoning),
      el("p", { className: "strength" }, el("b", { textContent: "Siła dowodów: " }), c.strength),
      c.premises.length ? el("ul", { className: "premises" }, ...c.premises.map((p) => el("li", { textContent: p }))) : null),
    c.limitations.length
      ? el("div", { className: "unknown" }, el("h3", { className: "unknown-title", textContent: "Czego nie ustaliliśmy" }),
          el("ul", {}, ...c.limitations.map((l) => el("li", { textContent: l }))))
      : null);
}

function chatText(check) {
  // Same answer as on the page, so the web and a pasted reply never disagree. Without a link the first
  // limitation says why (no sources connected, a source down), so the reply never reads as "nothing exists".
  const lines = check.claims.map((c) => {
    const link = c.sources.map((s) => safeUrl(s.url)).find(Boolean);
    const reason = !link && c.limitations[0] ? ` ${c.limitations[0]}` : "";
    return `„${c.claim}”: ${answerText(c)}${link ? ` ${link}` : reason}`;
  });
  return [...lines, "Odpowiedź z faktczyfejk.pl (prototyp)"].join("\n");
}

function copyButton(check) {
  const button = el("button", { type: "button", className: "copy-btn", textContent: "Skopiuj odpowiedź na czat" });
  button.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(chatText(check));
      button.textContent = "Skopiowano";
    } catch {
      button.textContent = "Nie udało się skopiować";
    }
    setTimeout(() => { button.textContent = "Skopiuj odpowiedź na czat"; }, 2500);
  });
  return button;
}

// Scenario I: a known incident the input looks like. Context only, never a verdict.
const MATCH_LABELS = { url: "ten sam adres", domain: "domena z bazy", text: "podobny tekst" };
const INCIDENT_NOTE = "Ta treść przypomina incydenty z bazy organizatora. "
  + "To tylko kontekst: nie zmienia oceny twierdzeń.";

function incidentItem(m) {
  const url = safeUrl(m.url);
  const how = MATCH_LABELS[m.matched_on] + (m.similarity != null ? ` ${Math.round(m.similarity * 100)}%` : "");
  return el("li", {}, m.incident_text, ` (${m.incident_id}, ${how})`,
    url ? el("span", {}, " ", el("a", { href: url, textContent: "adres", rel: "noopener noreferrer", target: "_blank" })) : null);
}

function incidentWarning(matches) {
  if (!matches?.length) return null;
  return el("section", { className: "incidents", role: "note" },
    el("h2", { textContent: "Podobne znane incydenty" }),
    el("p", { textContent: INCIDENT_NOTE }),
    el("ul", {}, ...matches.map(incidentItem)));
}

// One chip per verdict with its count, so a long answer can be read at a glance.
function summary(claims) {
  const counts = new Map();
  claims.forEach((c) => counts.set(c.verdict, { label: c.verdict_label, n: (counts.get(c.verdict)?.n ?? 0) + 1 }));
  if (counts.size < 2) return null;
  return el("p", { className: "summary" }, ...[...counts].map(([v, { label, n }]) =>
    el("span", { className: `verdict verdict-${v} small`, textContent: `${n} × ${label}` })));
}

// Measured time, and the model cost the API reports for this answer (models only; search credits excluded).
const USD = new Intl.NumberFormat("pl-PL", { style: "currency", currency: "USD", maximumFractionDigits: 4 });
function costLine(seconds, cost) {
  return typeof cost === "number" ? `w ${seconds} s, koszt modelu ${USD.format(cost)}` : `w ${seconds} s`;
}

function render(check, seconds) {
  const warning = incidentWarning(check.incident_matches);
  // Statuses other than "ok" are notices, never verdicts.
  if (check.status !== "ok") {
    const main = notice(NOTICE_TITLES[check.status] ?? "Brak oceny", check.message, NOT_A_VERDICT);
    const limits = check.limitations?.length
      ? el("ul", {}, ...check.limitations.map((l) => el("li", { textContent: l })))
      : null;
    if (!check.security_events?.length && !limits && !warning) return main;
    return el("div", {},
      check.security_events?.length ? notice("Polecenia dla modelu", SECURITY_NOTE_ONLY) : null,
      main, limits, warning);
  }
  const unchecked = check.unchecked_claims ?? [];
  if (!check.claims.length && !unchecked.length) {
    const empty = notice("Nie znaleźliśmy zdania do sprawdzenia",
      "Wklej fragment z konkretnym faktem, na przykład datą, liczbą albo nazwą instytucji.");
    return warning ? el("div", {}, empty, warning) : empty;
  }
  const events = check.security_events ?? [];
  return el("article", { className: "card" },
    events.some((e) => e.location !== "source") ? notice("Polecenia dla modelu", SECURITY_NOTE) : null,
    events.some((e) => e.location === "source") ? notice("Polecenia w źródle", SOURCE_SECURITY_NOTE) : null,
    el("div", { className: "card-head" },
      el("div", {},
        el("p", { className: "card-title" }, `Sprawdziliśmy ${plural(check.claims.length, "zdanie", "zdania", "zdań")} `,
          el("span", { className: "took", textContent: costLine(seconds, check.cost_usd) })),
        summary(check.claims)),
      copyButton(check)),
    check.page ? pageNote(check.page) : null,
    warning,
    ...check.claims.map(claimBlock),
    unchecked.length ? uncheckedList(unchecked) : null);
}

// The page behind a link: what was read, not evidence for its own claims.
function pageNote(p) {
  const meta = [p.publisher, plDate(p.published_at)].filter(Boolean).join(", ");
  const url = safeUrl(p.url);
  return el("p", { className: "origin" }, "Sprawdzony tekst pochodzi ze strony: ",
    url ? el("a", { href: url, textContent: p.title || url, rel: "noopener noreferrer", target: "_blank" }) : (p.title || p.url),
    meta ? `, ${meta}` : null, ". Ta strona nie jest źródłem dowodów dla własnych twierdzeń.");
}

function calm() {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

// Resolves once the new content is in the DOM, so callers can scroll to it.
function show(node) {
  const swap = () => {
    document.body.classList.add("checked");
    result.replaceChildren(node);
  };
  if (!document.startViewTransition || calm()) {
    swap();
    return Promise.resolve();
  }
  // A newer transition skips an older one; that is expected, not an error.
  const transition = document.startViewTransition(swap);
  transition.ready.catch(() => {});
  transition.finished.catch(() => {});
  return transition.updateCallbackDone.catch(() => {});
}

function reveal() {
  result.scrollIntoView({ behavior: calm() ? "auto" : "smooth", block: "start" });
}

async function errorMessage(resp) {
  try {
    const body = await resp.json();
    if (typeof body.detail === "string") return body.detail;
    if (resp.status === 422 && body.detail?.[0]?.msg) return body.detail[0].msg;
  } catch {}
  return GENERIC_ERROR;
}

// aria-disabled, not disabled: a disabled button drops keyboard focus. No aria-busy on #result:
// screen readers may skip updates made while it is set, and the waiting notice should be heard.
function setBusy(value) {
  busy = value;
  [submit, ...chips].forEach((control) => control.setAttribute("aria-disabled", String(value)));
}

// Cleared first so the same message is announced again on a repeated attempt.
function fieldError(message) {
  cancelAnimationFrame(errorFrame);
  formError.textContent = "";
  formError.hidden = !message;
  if (message) {
    input.setAttribute("aria-invalid", "true");
    errorFrame = requestAnimationFrame(() => { formError.textContent = message; });
  } else {
    input.removeAttribute("aria-invalid");
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (busy) return;
  const text = input.value.trim();
  if (!text || chars(text) > MAX_CHARS) {
    fieldError(text ? `Treść jest za długa. Limit to ${MAX_CHARS} znaków.` : "Wpisz tekst do sprawdzenia.");
    input.focus();
    return;
  }
  fieldError("");
  setBusy(true);
  const started = Date.now();
  const elapsed = () => Math.max(1, Math.round((Date.now() - started) / 1000));
  const waiting = notice("Sprawdzamy", "Szukamy w Google Fact Check, EUvsDisinfo, na www.gov.pl i w wyszukiwarce ograniczonej do zaufanych stron. Może to potrwać kilkadziesiąt sekund.");
  const seconds = el("p", { className: "note", textContent: "0 s" });
  seconds.setAttribute("aria-hidden", "true");
  waiting.append(seconds);
  const timer = setInterval(() => { seconds.textContent = `${elapsed()} s`; }, 1000);
  submit.setAttribute("aria-label", "Sprawdzamy…");
  show(waiting).then(reveal);
  try {
    const headers = { "Content-Type": "application/json" };
    const known = storedSession();
    if (known) headers["X-Session-Id"] = known;
    const resp = await fetch("/api/checks", {
      method: "POST",
      headers,
      body: JSON.stringify({ input: text }),
      signal: AbortSignal.timeout(75000),
    });
    rememberSession(resp.headers.get("X-Session-Id"));
    if (resp.ok) show(render(await resp.json(), elapsed()));
    else if (resp.status >= 500) show(notice("Błąd techniczny", GENERIC_ERROR, NOT_A_VERDICT));
    else show(notice("Nie możemy przyjąć tego zapytania", await errorMessage(resp)));
  } catch {
    show(notice("Błąd połączenia", GENERIC_ERROR, NOT_A_VERDICT));
  } finally {
    clearInterval(timer);
    submit.setAttribute("aria-label", "Sprawdź");
    setBusy(false);
  }
});

input.addEventListener("input", () => fieldError(""));
input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing && ENTER_SENDS.matches) {
    event.preventDefault();
    form.requestSubmit();
  }
});


// Demo session: the API issues an id on the first check; this tab sends it back and can delete it.
const SESSION_KEY = "prawdowid-session";
const sessionNote = document.getElementById("session");
const sessionStatus = document.getElementById("session-status");
const deleteSession = document.getElementById("delete-session");

// Browsers may deny storage (SecurityError); then the id lives in memory for this page only.
let sessionId = null;
try { sessionId = sessionStorage.getItem(SESSION_KEY); } catch { /* storage denied */ }
function storedSession() {
  return sessionId;
}
function storeSession(id) {
  sessionId = id;
  try {
    if (id) sessionStorage.setItem(SESSION_KEY, id);
    else sessionStorage.removeItem(SESSION_KEY);
  } catch { /* kept in memory */ }
}

function rememberSession(id) {
  if (!id) return;
  storeSession(id);
  sessionNote.hidden = false;
  deleteSession.hidden = false;
  sessionStatus.textContent = "";
}

deleteSession.addEventListener("click", async () => {
  const id = storedSession();
  if (!id) return;
  deleteSession.disabled = true;
  try {
    const resp = await fetch(`/api/sessions/${encodeURIComponent(id)}`, {
      method: "DELETE",
      signal: AbortSignal.timeout(10000),
    });
    if (!resp.ok) throw new Error(String(resp.status));
    storeSession(null);
    deleteSession.hidden = true;
    sessionStatus.textContent = "Usunęliśmy sprawdzenia z tej sesji.";
  } catch {
    sessionStatus.textContent = "Nie udało się usunąć sprawdzeń. Spróbuj ponownie za chwilę.";
  } finally {
    deleteSession.disabled = false;
  }
});

if (storedSession()) sessionNote.hidden = false;

chips.forEach((chip) => chip.addEventListener("click", () => {
  if (busy) return;
  input.value = chip.dataset.example;
  fieldError("");
  // The chips hide once a check starts, so keep keyboard focus in the box.
  input.focus();
  form.requestSubmit();
}));
