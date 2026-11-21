// Web channel: send the input to the API and render CheckResult. No verification logic here.
const form = document.getElementById("check-form");
const input = document.getElementById("input");
const count = document.getElementById("count");
const submit = document.getElementById("submit");
const result = document.getElementById("result");

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

function claimCard(c) {
  return el("article", { className: "claim" },
    el("h2", { className: "claim-text", textContent: c.claim }),
    el("p", {}, "Ocena: ",
      el("span", { className: `verdict verdict-${c.verdict}`, textContent: c.verdict_label })),
    el("h3", { textContent: "Uzasadnienie" }), el("p", { textContent: c.reasoning }),
    el("h3", { textContent: "Siła dowodów" }), el("p", { textContent: c.strength }),
    el("h3", { textContent: "Przesłanki" }), list(c.premises),
    el("h3", { textContent: "Źródła" }), el("ul", {}, ...c.sources.map(sourceItem)),
    c.limitations.length ? el("h3", { textContent: "Ograniczenia" }) : null,
    c.limitations.length ? list(c.limitations) : null);
}

function render(check) {
  // Statuses other than "ok" are notices, never verdicts.
  if (check.status !== "ok") return [box("notice", "Brak oceny", check.message)];
  if (!check.claims.length) return [box("notice", "Brak twierdzeń", "Usługa nie zwróciła żadnego twierdzenia.")];
  return check.claims.map(claimCard);
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
    const resp = await fetch("/api/checks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ input: input.value }),
      signal: AbortSignal.timeout(75000),
    });
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
