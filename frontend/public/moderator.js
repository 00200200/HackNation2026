// Moderator panel: list the cases the fact-checker could not answer and write a human answer to each.
const tokenForm = document.getElementById("token-form");
const tokenInput = document.getElementById("token");
const statusEl = document.getElementById("status");
const list = document.getElementById("cases");
const TOKEN_KEY = "prawdowid-moderator-token";
const MAX_ANSWER = 2000;
const MESSAGES = {
  401: "Nieprawidłowy token.",
  404: "Panel moderatora jest wyłączony na tym serwerze.",
};
const GENERIC_ERROR = "Nie udało się połączyć z usługą. Spróbuj ponownie za chwilę.";

try { tokenInput.value = sessionStorage.getItem(TOKEN_KEY) ?? ""; } catch { /* storage denied */ }

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  Object.assign(node, attrs);
  node.append(...children.filter((c) => c !== null && c !== undefined && c !== false));
  return node;
}

function plDateTime(value) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value
    : date.toLocaleString("pl-PL", { timeZone: "Europe/Warsaw", dateStyle: "short", timeStyle: "short" });
}

function say(message, isError = false) {
  statusEl.textContent = message;
  statusEl.classList.toggle("error", isError);
}

async function api(path, options = {}) {
  let resp;
  try {
    resp = await fetch(`/api/moderator/${path}`, {
      ...options,
      headers: { Authorization: `Bearer ${tokenInput.value.trim()}`, "Content-Type": "application/json" },
      signal: AbortSignal.timeout(15000),
    });
  } catch {
    throw new Error(GENERIC_ERROR); // network down or timed out
  }
  if (resp.ok) return resp.json();
  // The server's own Polish message first ("Nie ma takiej sprawy.", the rate limit, a validation error).
  const detail = (await resp.json().catch(() => ({}))).detail;
  const message = (typeof detail === "string" ? detail : detail?.[0]?.msg)
    ?? MESSAGES[resp.status] ?? GENERIC_ERROR;
  throw new Error(message);
}

function caseMeta(c) {
  return `Zadano ${c.asked === 1 ? "1 raz" : `${c.asked} razy`}, ostatnio ${plDateTime(c.last_asked)}. Status: `
    + (c.answer ? `odpowiedziana ${plDateTime(c.answered_at)}` : "otwarta");
}

// After a save only the meta line and the message change, so keyboard focus stays on the button.
function caseItem(c) {
  const item = el("li", { className: "mod-case" });
  const meta = el("p", { className: "mod-meta", id: `meta-${c.id}`, textContent: caseMeta(c) });
  const message = el("p", { className: "mod-msg", id: `msg-${c.id}`, role: "status" });
  const area = el("textarea", { id: `answer-${c.id}`, maxLength: MAX_ANSWER, value: c.answer ?? "" });
  area.setAttribute("aria-describedby", `meta-${c.id} hint-${c.id} msg-${c.id}`);
  const button = el("button", { type: "button", textContent: "Wyślij odpowiedź" });
  button.addEventListener("click", async () => {
    if (button.getAttribute("aria-disabled") === "true") return;
    button.setAttribute("aria-disabled", "true");
    message.classList.remove("error");
    message.textContent = "Zapisuję…";
    try {
      const saved = await api(`cases/${encodeURIComponent(c.id)}/answer`, { method: "POST", body: JSON.stringify({ answer: area.value }) });
      meta.textContent = caseMeta(saved);
      area.removeAttribute("aria-invalid");
      message.textContent = "Zapisano.";
    } catch (error) {
      area.setAttribute("aria-invalid", "true");
      message.classList.add("error");
      message.textContent = error.message;
    } finally {
      button.removeAttribute("aria-disabled");
    }
  });
  item.append(
    el("h2", { textContent: `Sprawa ${c.id}: ${c.question}` }),
    meta,
    el("label", { htmlFor: area.id, textContent: `Odpowiedź moderatora do sprawy ${c.id}` }),
    area,
    el("p", { className: "mod-meta", id: `hint-${c.id}`, textContent: `Do ${MAX_ANSWER} znaków.` }),
    button,
    message);
  return item;
}

async function load() {
  try { sessionStorage.setItem(TOKEN_KEY, tokenInput.value); } catch { /* kept in the field */ }
  say("Ładowanie…");
  try {
    const cases = await api("cases");
    list.replaceChildren(...cases.map(caseItem));
    say(cases.length ? `Liczba spraw: ${cases.length}.` : "Brak spraw.");
  } catch (error) {
    list.replaceChildren();
    say(error.message, true);
  }
}

tokenForm.addEventListener("submit", (event) => { event.preventDefault(); load(); });
if (tokenInput.value) load();
