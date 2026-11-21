// Web channel: send the input to the API and render CheckResult. No verification logic here.
const form = document.getElementById("check-form");
const input = document.getElementById("input");
const count = document.getElementById("count");
const submit = document.getElementById("submit");
const result = document.getElementById("result");

const SECURITY_NOTE = "Treść zawierała polecenia skierowane do modelu. Zignorowaliśmy je i sprawdziliśmy resztę.";
const SOURCE_SECURITY_NOTE = "W źródłach znaleźliśmy polecenia skierowane do modelu. Zignorowaliśmy je i sprawdziliśmy resztę.";
const SECURITY_NOTE_ONLY = "Treść zawierała polecenia skierowane do modelu. Zignorowaliśmy je.";
const GENERIC_ERROR = "Nie udało się połączyć z usługą. Spróbuj ponownie za chwilę.";

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  Object.assign(node, attrs);
  node.append(...children.filter((c) => c !== null && c !== undefined));
  return node;
}

function box(kind, title, text) {
  return el("div", { className: kind, role: kind === "error" ? "alert" : "status" },
    el("strong", { textContent: title }), text);
}

function list(items) {
  return el("ul", {}, ...items.map((item) => el("li", { textContent: item })));
}

function sourceItem(s) {
  const safeUrl = /^https?:\/\//.test(s.url) ? s.url : null;
  const title = safeUrl
    ? el("a", { href: safeUrl, textContent: s.title, rel: "noopener noreferrer", target: "_blank" })
    : s.title;
  const meta = [s.publisher, s.published_at].filter(Boolean).join(", ");
  return el("li", {}, title, meta ? `, ${meta}` : null,
    s.fragment ? el("q", { className: "fragment", textContent: s.fragment }) : null);
}

// Claims from a quote: who said it, and what was said. Plain statements get no tag.
const KIND_LABELS = { attribution: "Kto co powiedział", quoted: "Treść cytatu" };

function origin(c) {
  return el("p", { className: "origin" },
    KIND_LABELS[c.kind] ? el("span", { className: "kind", textContent: KIND_LABELS[c.kind] }) : null,
    `W tekście: ${c.source_sentence}`);
}

function claimCard(c) {
  return el("article", { className: "claim" },
    el("h2", { className: "claim-text", textContent: c.claim }),
    origin(c),
    el("p", {}, "Ocena: ",
      el("span", { className: `verdict verdict-${c.verdict}`, textContent: c.verdict_label })),
    el("h3", { textContent: "Uzasadnienie" }), el("p", { textContent: c.reasoning }),
    el("h3", { textContent: "Siła dowodów" }), el("p", { textContent: c.strength }),
    el("h3", { textContent: "Przesłanki" }), list(c.premises),
    el("h3", { textContent: "Źródła" }), el("ul", {}, ...c.sources.map(sourceItem)),
    c.limitations.length ? el("h3", { textContent: "Ograniczenia" }) : null,
    c.limitations.length ? list(c.limitations) : null);
}

// Scenario I: a known incident the input looks like. Context only, never a verdict.
const MATCH_LABELS = { url: "ten sam adres", domain: "domena z bazy", text: "podobny tekst" };

function incidentItem(m) {
  const safeUrl = m.url && /^https?:\/\//.test(m.url) ? m.url : null;
  const how = MATCH_LABELS[m.matched_on] + (m.similarity != null ? ` ${Math.round(m.similarity * 100)}%` : "");
  return el("li", {}, m.incident_text, ` (${m.incident_id}, ${how})`,
    safeUrl ? el("span", {}, " ", el("a", { href: safeUrl, textContent: "adres", rel: "noopener noreferrer", target: "_blank" })) : null);
}

function incidentWarning(matches) {
  return el("section", { className: "incidents", role: "note" },
    el("h2", { textContent: "Podobne znane incydenty" }),
    el("p", { textContent: INCIDENT_NOTE }),
    el("ul", {}, ...matches.map(incidentItem)));
}

const INCIDENT_NOTE = "Ta treść przypomina incydenty z bazy organizatora. "
  + "To tylko kontekst: nie zmienia oceny twierdzeń.";

function render(check) {
  const warning = check.incident_matches?.length ? [incidentWarning(check.incident_matches)] : [];
  // Statuses other than "ok" are notices, never verdicts.
  if (check.status !== "ok") {
    const notice = [box("notice", "Brak oceny", check.message)];
    if (check.security_events?.length) notice.unshift(box("notice", "Polecenia dla modelu", SECURITY_NOTE_ONLY));
    return [...notice, ...warning];
  }
  if (!check.claims.length && !check.unchecked_claims?.length) return [box("notice", "Brak twierdzeń", "Usługa nie zwróciła żadnego twierdzenia."), ...warning];
  const events = check.security_events || [];
  const nodes = [];
  if (events.some((e) => e.location !== "source")) nodes.push(box("notice", "Polecenia dla modelu", SECURITY_NOTE));
  if (events.some((e) => e.location === "source")) nodes.push(box("notice", "Polecenia w źródle", SOURCE_SECURITY_NOTE));
  nodes.push(...warning, ...check.claims.map(claimCard));
  if (check.page) nodes.unshift(pageNote(check.page));
  if (check.unchecked_claims?.length) nodes.push(uncheckedList(check.unchecked_claims));
  return nodes;
}

// The page behind a link: what was read, not evidence for its own claims.
function pageNote(p) {
  const meta = [p.publisher, p.published_at].filter(Boolean).join(", ");
  return el("p", { className: "origin" }, "Sprawdzony tekst pochodzi ze strony: ",
    el("a", { href: p.url, textContent: p.title || p.url, rel: "noopener noreferrer", target: "_blank" }),
    meta ? `, ${meta}` : null, ". Ta strona nie jest źródłem dowodów dla własnych twierdzeń.");
}

function uncheckedList(claims) {
  return el("section", { className: "unchecked" },
    el("h2", { textContent: "Niesprawdzone twierdzenia" }),
    el("p", { textContent: "Jedno sprawdzenie obejmuje tylko najważniejsze twierdzenia z tekstu. "
      + "Tych nie oceniliśmy. Możesz wkleić je osobno." }),
    list(claims));
}

async function errorMessage(resp) {
  try {
    const body = await resp.json();
    if (typeof body.detail === "string") return body.detail;
    if (resp.status === 422 && body.detail?.[0]?.msg) return body.detail[0].msg;
  } catch {}
  return GENERIC_ERROR;
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  submit.disabled = true;
  submit.textContent = "Sprawdzam…";
  result.setAttribute("aria-busy", "true");
  try {
    const headers = { "Content-Type": "application/json" };
    const known = sessionStorage.getItem(SESSION_KEY);
    if (known) headers["X-Session-Id"] = known;
    const resp = await fetch("/api/checks", {
      method: "POST",
      headers,
      body: JSON.stringify({ input: input.value }),
      signal: AbortSignal.timeout(75000),
    });
    rememberSession(resp.headers.get("X-Session-Id"));
    let nodes;
    if (resp.ok) nodes = render(await resp.json());
    else if (resp.status >= 500) nodes = [box("error", "Błąd techniczny", GENERIC_ERROR)];
    else nodes = [box("error", "Nie możemy przyjąć tego zapytania", await errorMessage(resp))];
    result.replaceChildren(...nodes);
  } catch {
    result.replaceChildren(box("error", "Błąd połączenia", GENERIC_ERROR));
  } finally {
    submit.disabled = false;
    submit.textContent = "Sprawdź";
    result.removeAttribute("aria-busy");
  }
});

input.addEventListener("input", () => { count.textContent = input.value.length; });

// Demo session: the API issues an id on the first check; this tab sends it back and can delete it.
const SESSION_KEY = "prawdowid-session";
const sessionNote = document.getElementById("session");
const sessionStatus = document.getElementById("session-status");
const deleteSession = document.getElementById("delete-session");

function rememberSession(id) {
  if (!id) return;
  sessionStorage.setItem(SESSION_KEY, id);
  sessionNote.hidden = false;
  deleteSession.hidden = false;
  sessionStatus.textContent = "";
}

deleteSession.addEventListener("click", async () => {
  const id = sessionStorage.getItem(SESSION_KEY);
  if (!id) return;
  deleteSession.disabled = true;
  try {
    const resp = await fetch(`/api/sessions/${encodeURIComponent(id)}`, {
      method: "DELETE",
      signal: AbortSignal.timeout(10000),
    });
    if (!resp.ok) throw new Error(String(resp.status));
    sessionStorage.removeItem(SESSION_KEY);
    deleteSession.hidden = true;
    sessionStatus.textContent = "Usunęliśmy sprawdzenia z tej sesji.";
  } catch {
    sessionStatus.textContent = "Nie udało się usunąć sprawdzeń. Spróbuj ponownie za chwilę.";
  } finally {
    deleteSession.disabled = false;
  }
});

if (sessionStorage.getItem(SESSION_KEY)) sessionNote.hidden = false;
