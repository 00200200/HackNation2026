// Messenger demo adapter at /czat (#116). It sends the same POST /api/checks as the web form and the Discord
// bot, as X-Channel: demo, and shows the CheckResult as chat messages in the order of
// prawdowid/discord_bot.render(). No verification logic here. tests/test_czat.py keeps the notices word for
// word in step with the bot, and the first words of each answer with the web page (app.js).
const thread = document.getElementById("thread");
const form = document.getElementById("composer");
const input = document.getElementById("message");
const send = document.getElementById("send");
const formError = document.getElementById("composer-error");
const examples = document.querySelectorAll("[data-example]");
const deleteSession = document.getElementById("delete-session");
const sessionStatus = document.getElementById("session-status");

const CHANNEL = "demo";
// MAX_INPUT_CHARS of prawdowid/app.py; the bot's API_TIMEOUT_S, above the API's 60 s limit.
const MAX_CHARS = 5000;
const API_TIMEOUT_MS = 75000;

// Word for word from prawdowid/discord_bot.py and prawdowid/app.py.
const SECURITY_NOTE = "W treści są zwroty, które wyglądają na polecenia dla modelu. Nie wykonaliśmy ich i sprawdziliśmy resztę.";
const SECURITY_NOTE_ONLY = "W treści są zwroty, które wyglądają na polecenia dla modelu. Nie wykonaliśmy ich.";
const SOURCE_SECURITY_NOTE = "W źródłach są zwroty, które wyglądają na polecenia dla modelu. Nie wykonaliśmy ich i sprawdziliśmy resztę.";
const PAGE_NOTE = "Ta strona nie jest źródłem dowodów dla własnych twierdzeń.";
const UNCHECKED_NOTE = "Jedno sprawdzenie obejmuje tylko najważniejsze twierdzenia z tekstu. Tych nie oceniliśmy. Możesz wkleić je osobno.";
const INCIDENT_NOTE = "Ta treść przypomina incydenty z bazy organizatora. To tylko kontekst: nie zmienia oceny twierdzeń.";
const CONNECTION_ERROR = "Nie udało się połączyć z usługą. Spróbuj ponownie za chwilę.";
const TECHNICAL_ERROR_MESSAGE = "Wystąpił błąd techniczny i nie udało się sprawdzić tej treści. Spróbuj ponownie za chwilę.";
const KIND_LABELS = { attribution: "Kto co powiedział", quoted: "Treść cytatu" };
const MATCH_LABELS = { url: "ten sam adres", domain: "domena z bazy", text: "podobny tekst" };
// First words of the answer in the organiser's format, the same as on the web page.
const ANSWER_LEAD = {
  confirmed: "Tak.",
  false: "Nie.",
  misleading: "To wprowadza w błąd.",
  insufficient_evidence: "Nie udało mi się potwierdzić tej informacji.",
  not_verifiable: "Tego nie da się sprawdzić: to opinia, prognoza albo pytanie bez faktu do sprawdzenia.",
  not_checked: "Nie sprawdziliśmy tego twierdzenia.",
};
// Enter sends only with a hardware keyboard; on touch keyboards it adds a new line.
const ENTER_SENDS = window.matchMedia("(hover: hover) and (pointer: fine)");
const LINK = { rel: "noopener noreferrer", target: "_blank" };
let busy = false;
let errorFrame = 0;

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  Object.assign(node, attrs);
  node.append(...children.flat(Infinity).filter((c) => c !== null && c !== undefined && c !== false));
  return node;
}

// The API counts characters, not UTF-16 units: an emoji is one character.
function chars(text) {
  return [...text].length;
}

function plDate(value) {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString("pl-PL", { timeZone: "Europe/Warsaw" });
}

function safeUrl(url) {
  return /^https?:\/\//.test(url ?? "") ? url : null;
}

function host(url) {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return null;
  }
}

function clock() {
  return new Date().toLocaleTimeString("pl-PL", { hour: "2-digit", minute: "2-digit" });
}

function calm() {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

// The same sentence as the answer on the web page: the first words, then who says so.
function answerText(c) {
  const publishers = [...new Set(c.sources.map((s) => s.publisher).filter(Boolean))];
  const named = publishers.length ? `${publishers.length === 1 ? "Źródło" : "Źródła"}: ${publishers.join(", ")}.` : null;
  return [ANSWER_LEAD[c.verdict] ?? `${c.verdict_label}.`, named].filter(Boolean).join(" ");
}

function list(items) {
  return el("ul", {}, ...items.map((item) => el("li", {}, item)));
}

function part(title, body) {
  return [el("h3", { className: "m-part", textContent: title }), body];
}

// A line that starts with its name in bold, as "**Uzasadnienie:** ..." in the bot's message.
function named(name, text) {
  return el("p", {}, el("b", { textContent: name }), text ? ` ${text}` : null);
}

// A bot message; "msg-notice" for anything that is not an answer about a claim.
function bubble(kind, ...children) {
  return el("div", { className: `msg msg-bot ${kind}`.trim() }, ...children);
}

function sourceItem(s, i) {
  const url = safeUrl(s.url);
  const meta = [
    s.publisher,
    s.published_at ? plDate(s.published_at) : "bez daty publikacji",
    url ? host(url) : null,
  ].filter(Boolean).join(", ");
  return el("li", {},
    el("p", { className: "src-head" }, el("span", { className: "ref", textContent: `[${i + 1}]` }), " ",
      url ? el("a", { ...LINK, href: url, textContent: s.title }) : s.title),
    el("p", { className: "src-meta", textContent: meta }),
    s.fragment ? el("blockquote", { className: "quote", textContent: `„${s.fragment}”` }) : null);
}

function claimBubble(n, c) {
  // "nie sprawdzono" is no verdict: it must not read like one.
  const rated = c.verdict === "not_checked" ? "Bez oceny" : "Ocena";
  return bubble("",
    el("h2", { className: "m-title", textContent: `${n}. „${c.claim}”` }),
    el("p", { className: "m-origin" },
      KIND_LABELS[c.kind] ? [el("span", { className: "kind", textContent: KIND_LABELS[c.kind] }), " "] : null,
      `W tekście: ${c.source_sentence}`),
    el("p", { className: "m-lead", textContent: answerText(c) }),
    el("p", { className: "m-verdict" }, `${rated}:`,
      el("span", { className: `verdict verdict-${c.verdict}`, textContent: c.verdict_label })),
    c.reasoning ? named("Uzasadnienie:", c.reasoning) : null,
    c.strength ? named("Siła dowodów:", c.strength) : null,
    c.premises.length ? part("Przesłanki", list(c.premises)) : null,
    part("Źródła", c.sources.length
      ? el("ol", { className: "m-sources" }, ...c.sources.map(sourceItem))
      : el("p", { textContent: "brak" })),
    c.limitations.length ? part("Ograniczenia", list(c.limitations)) : null);
}

// The page behind a link: what was read, not evidence for its own claims.
function pageBubble(p) {
  const url = safeUrl(p.url);
  const title = p.title || p.url;
  const meta = [p.publisher, plDate(p.published_at)].filter(Boolean).join(", ");
  return bubble("msg-notice", el("p", {}, "Sprawdzony tekst pochodzi ze strony: ",
    url ? el("a", { ...LINK, href: url, textContent: title }) : title, meta ? `, ${meta}` : null, `. ${PAGE_NOTE}`));
}

// Scenario I: a known incident the input looks like. Context only, never a verdict.
function incidentsBubble(matches) {
  return bubble("msg-notice",
    el("h2", { className: "m-title", textContent: "Podobne znane incydenty" }),
    el("p", { textContent: INCIDENT_NOTE }),
    list(matches.map((m) => {
      const url = safeUrl(m.url);
      const how = (MATCH_LABELS[m.matched_on] ?? m.matched_on) + (m.similarity != null ? ` ${Math.round(m.similarity * 100)}%` : "");
      return [`${m.incident_text} (${m.incident_id}, ${how})`, url ? [" ", el("a", { ...LINK, href: url, textContent: url })] : null];
    })));
}

function securityBubble(note) {
  return bubble("msg-notice", named("Polecenia dla modelu.", note));
}

// prawdowid/discord_bot.render(): one message per section, in the bot's order.
function replyBubbles(check) {
  const warning = check.incident_matches?.length ? [incidentsBubble(check.incident_matches)] : [];
  // Statuses other than "ok" are notices, never verdicts.
  if (check.status !== "ok") {
    return [bubble("msg-notice",
      check.security_events?.length ? named("Polecenia dla modelu.", SECURITY_NOTE_ONLY) : null,
      named("Brak oceny.", check.message),
      // A label, not a heading: this message has no claim heading to sit under.
      check.limitations?.length ? [named("Ograniczenia:"), list(check.limitations)] : null), ...warning];
  }
  const claims = check.claims ?? [];
  const unchecked = check.unchecked_claims ?? [];
  if (!claims.length && !unchecked.length) {
    return [bubble("msg-notice", named("Brak twierdzeń.", "Usługa nie zwróciła żadnego twierdzenia.")), ...warning];
  }
  const locations = new Set((check.security_events ?? []).map((e) => e.location));
  return [
    check.page ? pageBubble(check.page) : null,
    [...locations].some((l) => l !== "source") ? securityBubble(SECURITY_NOTE) : null,
    locations.has("source") ? securityBubble(SOURCE_SECURITY_NOTE) : null,
    ...warning,
    ...claims.map((c, i) => claimBubble(i + 1, c)),
    unchecked.length
      ? bubble("msg-notice", el("h2", { className: "m-title", textContent: "Niesprawdzone twierdzenia" }),
          el("p", { textContent: UNCHECKED_NOTE }), list(unchecked))
      : null,
  ].filter(Boolean);
}

function asNotice(status, message) {
  return { status, message };
}

// prawdowid/discord_bot.ask_api(): the same request, and any failure becomes a notice, never a verdict.
async function ask(text) {
  const headers = { "Content-Type": "application/json", "X-Channel": CHANNEL };
  if (sessionId) headers["X-Session-Id"] = sessionId;
  let resp;
  try {
    resp = await fetch("/api/checks", {
      method: "POST",
      headers,
      body: JSON.stringify({ input: text }),
      signal: AbortSignal.timeout(API_TIMEOUT_MS),
    });
  } catch {
    return asNotice("technical_error", CONNECTION_ERROR);
  }
  rememberSession(resp.headers.get("X-Session-Id"));
  if (resp.status === 422 || resp.status === 429) {
    // Input rejected or rate limited: the API's Polish message, shown as a notice.
    try {
      const { detail } = await resp.json();
      const message = typeof detail === "string" ? detail : detail?.[0]?.msg;
      return asNotice("cannot_check", typeof message === "string" && message ? message : TECHNICAL_ERROR_MESSAGE);
    } catch {
      return asNotice("cannot_check", TECHNICAL_ERROR_MESSAGE);
    }
  }
  try {
    if (!resp.ok) throw new Error(String(resp.status));
    const check = await resp.json();
    if (typeof check?.status !== "string") throw new Error("not a CheckResult");
    return check;
  } catch {
    return asNotice("technical_error", TECHNICAL_ERROR_MESSAGE);
  }
}

// One sender's messages; the hidden name tells screen reader users who wrote them.
function group(side, bubbles, meta) {
  bubbles.at(-1)?.classList.add("tail");
  return el("div", { className: `group group-${side}` },
    el("p", { className: "sr-only", textContent: side === "user" ? "Ty:" : "faktczyfejk:", translate: side === "user" }),
    ...bubbles,
    meta ? el("p", { className: "time", textContent: meta }) : null);
}

function typingGroup() {
  const seconds = el("span", { className: "typing-time", textContent: "0\u00a0s" });
  // The ticking counter is for the eyes only: the log must not announce every second.
  seconds.setAttribute("aria-hidden", "true");
  const dots = el("span", { className: "dots" }, el("span"), el("span"), el("span"));
  dots.setAttribute("aria-hidden", "true");
  const node = group("bot", [bubble("typing", dots, el("span", { textContent: "Sprawdzamy… Może to potrwać kilkadziesiąt sekund." }), seconds)]);
  const started = Date.now();
  const timer = setInterval(() => { seconds.textContent = `${Math.round((Date.now() - started) / 1000)}\u00a0s`; }, 1000);
  return { node, stop: () => clearInterval(timer) };
}

async function converse(text) {
  setBusy(true);
  const behavior = calm() ? "auto" : "smooth";
  const typing = typingGroup();
  thread.append(group("user", [el("div", { className: "msg msg-user", textContent: text })], clock()), typing.node);
  typing.node.scrollIntoView({ block: "end", behavior });
  const started = Date.now();
  let bubbles;
  try {
    bubbles = replyBubbles(await ask(text));
  } catch {
    // A body that passed as a CheckResult but cannot be shown: a notice, as when the bot cannot read it.
    bubbles = replyBubbles(asNotice("technical_error", TECHNICAL_ERROR_MESSAGE));
  }
  typing.stop();
  const seconds = Math.max(1, Math.round((Date.now() - started) / 1000));
  const answer = group("bot", bubbles, `${clock()}, po ${seconds}\u00a0s`);
  typing.node.replaceWith(answer);
  answer.scrollIntoView({ block: "start", behavior });
  setBusy(false);
}

// aria-disabled, not disabled: a disabled button drops keyboard focus.
function setBusy(value) {
  busy = value;
  [send, ...examples, deleteSession].forEach((control) => control.setAttribute("aria-disabled", String(value)));
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

form.addEventListener("submit", (event) => {
  event.preventDefault();
  if (busy) return;
  const text = input.value.trim();
  if (!text || chars(text) > MAX_CHARS) {
    fieldError(text ? `Treść jest za długa. Limit to ${MAX_CHARS} znaków.` : "Wpisz tekst do sprawdzenia.");
    input.focus();
    return;
  }
  fieldError("");
  input.value = "";
  input.style.removeProperty("height");
  // With a hardware keyboard the composer stays ready, as in a desktop messenger; on a phone the keyboard
  // closes after sending, so the reply is not hidden under it.
  if (ENTER_SENDS.matches) input.focus();
  converse(text);
});

// The composer grows with its text up to its max-height: CSS field-sizing does it where supported (Chromium),
// this does it in Safari and Firefox.
const GROWS_BY_ITSELF = CSS.supports("field-sizing", "content");
input.addEventListener("input", () => {
  fieldError("");
  if (GROWS_BY_ITSELF) return;
  input.style.height = "auto";
  input.style.height = `${input.scrollHeight}px`;
});
input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing && ENTER_SENDS.matches) {
    event.preventDefault();
    form.requestSubmit();
  }
});

// A quick reply is sent as the user's own message. Focus moves to the composer as after sending.
examples.forEach((chip) => chip.addEventListener("click", () => {
  if (busy) return;
  fieldError("");
  if (ENTER_SENDS.matches) input.focus();
  converse(chip.dataset.example);
}));

// Demo session, apart from the web page's: the API issues an id on the first check, this tab sends it back
// and can delete it (DELETE /api/sessions/{id}). Storage may be denied; then the id lives in memory only.
const SESSION_KEY = "prawdowid-czat-session";
let sessionId = null;
try { sessionId = sessionStorage.getItem(SESSION_KEY); } catch { /* storage denied */ }

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
  deleteSession.hidden = false;
  sessionStatus.textContent = "";
}

let deleting = false;
deleteSession.addEventListener("click", async () => {
  // Not while a check runs: its response would bring the deleted session back.
  if (!sessionId || busy || deleting) return;
  deleting = true;
  deleteSession.setAttribute("aria-disabled", "true");
  try {
    const resp = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}`, {
      method: "DELETE",
      signal: AbortSignal.timeout(10000),
    });
    if (!resp.ok) throw new Error(String(resp.status));
    storeSession(null);
    deleteSession.hidden = true;
    input.focus();
    sessionStatus.textContent = "Usunęliśmy sprawdzenia z tej sesji.";
  } catch {
    sessionStatus.textContent = "Nie udało się usunąć sprawdzeń. Spróbuj ponownie za chwilę.";
  } finally {
    deleting = false;
    deleteSession.setAttribute("aria-disabled", "false");
  }
});

if (sessionId) deleteSession.hidden = false;
