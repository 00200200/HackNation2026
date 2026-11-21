// Web channel: send the input to the API and render CheckResult. No verification logic here.
const form = document.getElementById("check-form");
const input = document.getElementById("input");
const count = document.getElementById("count");
const submit = document.getElementById("submit");
const formError = document.getElementById("form-error");
const result = document.getElementById("result");
const example = document.getElementById("przyklad");
const chips = document.querySelectorAll("[data-example]");

const MAX_CHARS = 5000;
const GENERIC_ERROR = "Nie udało się połączyć z usługą. Spróbuj ponownie za chwilę.";
const NOT_A_VERDICT = "To nie jest ocena prawdziwości tej treści.";
const NOTICE_TITLES = {
  technical_error: "Nie udało się sprawdzić",
  cannot_check: "Nie możemy tego sprawdzić",
  needs_clarification: "Doprecyzuj, co chcesz sprawdzić",
};
const PLURAL = new Intl.PluralRules("pl-PL");

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
function notice(title, text, note) {
  return el("div", { className: "notice", role: "status" },
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
  const meta = [
    host,
    s.published_at ? `opublikowano ${plDate(s.published_at)}` : "bez daty publikacji",
    s.fetched_at ? `pobrano ${plDate(s.fetched_at)}` : null,
    s.source_type,
  ].filter(Boolean).join(", ");
  return el("li", { className: "source" },
    s.fragment ? el("blockquote", { className: "quote", textContent: `„${s.fragment}”` }) : null,
    el("p", { className: "source-head" }, el("span", { className: "ref", textContent: `[${i + 1}]` }), " ",
      s.publisher ? el("b", { textContent: s.publisher }) : null, s.publisher ? ", " : null, title),
    el("p", { className: "source-meta", textContent: meta }));
}

function claimBlock(c) {
  return el("div", { className: "claim" },
    el("h2", { className: "claim-text", textContent: `„${c.claim}”` }),
    el("p", { className: "claim-meta" },
      el("span", { className: `verdict verdict-${c.verdict}`, textContent: c.verdict_label })),
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
  const lines = check.claims.map((c) => {
    const link = c.sources.map((s) => safeUrl(s.url)).find(Boolean);
    const reason = !link && c.limitations[0] ? ` ${c.limitations[0]}` : "";
    return `„${c.claim}”: ${c.verdict_label}.${link ? ` Źródło: ${link}` : reason}`;
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

function render(check, seconds) {
  // Statuses other than "ok" are notices, never verdicts.
  if (check.status !== "ok") {
    return notice(NOTICE_TITLES[check.status] ?? "Brak oceny", check.message, NOT_A_VERDICT);
  }
  if (!check.claims.length) return notice("Brak twierdzeń", "Usługa nie zwróciła żadnego twierdzenia.");
  return el("article", { className: "card" },
    el("div", { className: "card-head" },
      el("p", { className: "card-title" }, `Sprawdziliśmy ${plural(check.claims.length, "zdanie", "zdania", "zdań")} `,
        el("span", { className: "took", textContent: `w ${seconds} s` })),
      copyButton(check)),
    ...check.claims.map(claimBlock));
}

function calm() {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

// Resolves once the new content is in the DOM, so callers can scroll to it.
function show(node) {
  const swap = () => {
    example.hidden = true;
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

function setBusy(busy) {
  submit.disabled = busy;
  chips.forEach((chip) => { chip.disabled = busy; });
  if (busy) result.setAttribute("aria-busy", "true");
  else result.removeAttribute("aria-busy");
}

function fieldError(message) {
  formError.textContent = message;
  formError.hidden = !message;
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (submit.disabled) return;
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
  const waiting = notice("Sprawdzamy", "Analizujemy wiadomość.");
  const seconds = el("p", { className: "note", textContent: "0 s" });
  seconds.setAttribute("aria-hidden", "true");
  waiting.append(seconds);
  const timer = setInterval(() => { seconds.textContent = `${elapsed()} s`; }, 1000);
  submit.textContent = "Sprawdzamy…";
  show(waiting).then(reveal);
  try {
    const resp = await fetch("/api/checks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ input: input.value }),
      signal: AbortSignal.timeout(75000),
    });
    if (resp.ok) show(render(await resp.json(), elapsed()));
    else if (resp.status >= 500) show(notice("Błąd techniczny", GENERIC_ERROR, NOT_A_VERDICT));
    else show(notice("Nie możemy przyjąć tego zapytania", await errorMessage(resp)));
  } catch {
    show(notice("Błąd połączenia", GENERIC_ERROR, NOT_A_VERDICT));
  } finally {
    clearInterval(timer);
    submit.textContent = "Sprawdź";
    setBusy(false);
  }
});

function updateCount() {
  count.textContent = chars(input.value);
}

updateCount();
input.addEventListener("input", () => { updateCount(); fieldError(""); });
input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    form.requestSubmit();
  }
});

chips.forEach((chip) => chip.addEventListener("click", () => {
  input.value = chip.dataset.example;
  updateCount();
  form.requestSubmit();
}));
