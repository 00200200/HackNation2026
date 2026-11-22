// Web channel: send the input to the API and render CheckResult. No verification logic here.
// SOURCE_TYPES, el, plural, plDate and safeUrl come from common.js, loaded first.
const form = document.getElementById("check-form");
const input = document.getElementById("input");
const submit = document.getElementById("submit");
const formError = document.getElementById("form-error");
const result = document.getElementById("result");
const chips = document.querySelectorAll("[data-example]");
const attachButton = document.getElementById("attach");
const fileInput = document.getElementById("image-file");
const preview = document.getElementById("preview");
const previewImg = document.getElementById("preview-img");
const previewName = document.getElementById("preview-name");
const removeImage = document.getElementById("remove-image");
const imageStatus = document.getElementById("image-status");

const SECURITY_NOTE = "W treści są zwroty, które wyglądają na polecenia dla modelu. Nie wykonaliśmy ich i sprawdziliśmy resztę.";
const SOURCE_SECURITY_NOTE = "W źródłach są zwroty, które wyglądają na polecenia dla modelu. Nie wykonaliśmy ich i sprawdziliśmy resztę.";
const SECURITY_NOTE_ONLY = "W treści są zwroty, które wyglądają na polecenia dla modelu. Nie wykonaliśmy ich.";
const MAX_CHARS = 5000;
// Same limits as the API (prawdowid/image_input.py), so a file it would refuse is never sent.
const IMAGE_TYPES = ["image/png", "image/jpeg", "image/webp"];
const MAX_IMAGE_BYTES = 5 * 1024 * 1024;
const GENERIC_ERROR = "Nie udało się połączyć z usługą. Spróbuj ponownie za chwilę.";
const NOT_A_VERDICT = "To nie jest ocena prawdziwości tej treści.";
const NOTICE_TITLES = {
  technical_error: "Nie udało się sprawdzić",
  cannot_check: "Nie możemy tego sprawdzić",
  needs_clarification: "Doprecyzuj, co chcesz sprawdzić",
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
// The attached image: { data: base64 without the data: prefix, name }, or null.
let image = null;

// The API counts characters, not UTF-16 units: an emoji is one character.
function chars(text) {
  return [...text].length;
}

// Anything that is not a verdict: neutral look, never the colours of a verdict.
// No role here: the #result region is already aria-live, a second live role would announce it twice.
function notice(title, text, note) {
  return el("div", { className: "notice" },
    el("strong", { textContent: title }),
    text ? el("span", { textContent: text }) : null,
    note ? el("p", { className: "note", textContent: note }) : null);
}

// A fact-checker's rating comes from its ClaimReview record: shown as the rating, never as a quote.
function sourceText(s) {
  if (s.rating) {
    return el("p", { className: "rating" }, el("b", { textContent: "Ocena fact-checkera: " }), s.rating);
  }
  return s.fragment ? el("blockquote", { className: "quote", textContent: `„${s.fragment}”` }) : null;
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
  // snippet_only: we could not read the page, so the quote is the search engine's extract of it
  // and fetched_at is when we searched. It holds the reason, e.g. "strona nie pozwala na pobranie".
  const snippet = Boolean(s.snippet_only);
  const meta = [
    host,
    s.published_at ? `opublikowano ${plDate(s.published_at)}` : "bez daty publikacji",
    s.fetched_at ? `${snippet ? "wyszukano" : "pobrano"} ${plDate(s.fetched_at)}` : null,
    SOURCE_TYPES[s.source_type] ?? s.source_type,
  ].filter(Boolean).join(", ");
  return el("li", { className: "source" },
    sourceText(s),
    el("p", { className: "source-head" }, el("span", { className: "ref", textContent: `[${i + 1}]` }), " ",
      s.publisher ? el("b", { textContent: s.publisher }) : null, s.publisher ? ", " : null, title),
    el("p", { className: "source-meta" },
      archival ? el("span", { className: "archival", textContent: `materiał archiwalny, ${year}` }) : null,
      archival ? " " : null,
      snippet ? el("span", { className: "snippet", textContent: `fragment z wyników wyszukiwarki; ${s.snippet_only}` }) : null,
      snippet ? " " : null, meta));
}

// The evidence chain (#78): sources grouped by the side their verified quote stands on (`stance`, set by
// judge.decide() in the API). The heading names the side in words; the icon and the colour only help. A source
// the verdict rules set aside has no stance. An answer with no stance at all keeps one plain list, as before.
// The same groups, in the same order, as /czat and the Discord bot.
const SIDES = [
  ["potwierdza", "Potwierdza"],
  ["przeczy", "Przeczy"],
  ["kontekst", "Uzupełnia kontekst"],
  [null, "Nie wpływa na ocenę"],
];
const NOT_COUNTED_NOTE = "Na przykład sam nagłówek albo starsza ocena tego samego fact-checkera.";
const SIDE_ICONS = { potwierdza: "M5 12.5l4.5 4.5L19 7.5", przeczy: "M7 7l10 10M17 7L7 17", kontekst: "M12 6v12M6 12h12" };
let sideCount = 0;

function sideOf(s) {
  return SIDES.some(([key]) => key && key === s.stance) ? s.stance : null;
}

function sideIcon(key) {
  if (!SIDE_ICONS[key]) return null;
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  const path = document.createElementNS(ns, "path");
  path.setAttribute("d", SIDE_ICONS[key]);
  svg.append(path);
  const icon = el("span", { className: "side-icon" }, svg);
  icon.setAttribute("aria-hidden", "true");
  return icon;
}

function sourcesBlock(sources) {
  if (!sources.length) return el("p", { className: "empty", textContent: "Brak źródła przy tej ocenie." });
  if (!sources.some(sideOf)) return el("ol", { className: "sources" }, ...sources.map(sourceItem));
  // One numbering across the groups, so [n] still names one source of the claim.
  let n = 0;
  const groups = {};
  for (const [key, title] of SIDES) {
    const items = sources.filter((s) => sideOf(s) === key);
    if (!items.length) continue;
    const id = `strona-${++sideCount}`;
    const list = el("ol", { className: "sources", start: n + 1 }, ...items.map((s) => sourceItem(s, n++)));
    list.setAttribute("aria-labelledby", id);
    groups[key ?? "none"] = el("div", { className: `side side-${key ?? "none"}` },
      el("h4", { className: "side-title", id }, sideIcon(key), title),
      key ? null : el("p", { className: "side-note", textContent: NOT_COUNTED_NOTE }),
      list);
  }
  // Both sides of a conflict next to each other (one under the other on a narrow screen).
  const sides = groups.potwierdza && groups.przeczy
    ? el("div", { className: "sides" }, groups.potwierdza, groups.przeczy)
    : groups.potwierdza ?? groups.przeczy;
  return el("div", { className: "chain" }, sides, groups.kontekst, groups.none);
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

// Under every claim's sources: what we search and why. A new tab, so the answer stays where it was.
function sourcesNote() {
  return el("p", { className: "sources-note" },
    el("a", { href: "/zrodla", target: "_blank", rel: "noopener" }, "Jak dobieramy źródła",
      el("span", { className: "sr-only", textContent: " (otwiera się w nowej karcie)" })));
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
    sourcesBlock(c.sources),
    sourcesNote(),
    el("h3", { className: "part", textContent: "Nasza ocena" }),
    el("div", { className: "assessment" },
      el("p", { className: "explain" }, el("b", { textContent: "Uzasadnienie: " }), c.reasoning),
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

// Export (#86): the JSON is the API answer as it came, the STIX 2.1 bundle is built by the API from that
// same answer (masked data only). Both download as files; nothing else leaves the page.
function download(name, type, text) {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const link = el("a", { href: url, download: name });
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function exportButtons(check) {
  const json = el("button", { type: "button", className: "copy-btn secondary", textContent: "Pobierz wynik (JSON)" });
  json.addEventListener("click", () => download("faktczyfejk-wynik.json", "application/json", JSON.stringify(check, null, 2)));
  // The API builds a bundle only from an ok answer with checked claims (prawdowid/export.py).
  if (check.status !== "ok" || !(check.claims || []).length) return [json];
  const stix = el("button", { type: "button", className: "copy-btn secondary", textContent: "Pobierz STIX 2.1" });
  stix.addEventListener("click", async () => {
    const label = "Pobierz STIX 2.1";
    try {
      const resp = await fetch("/api/export/stix", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(check),
        signal: AbortSignal.timeout(15000),
      });
      if (!resp.ok) throw new Error(String(resp.status));
      download("faktczyfejk-stix.json", "application/stix+json", await resp.text());
    } catch {
      stix.textContent = "Nie udało się pobrać";
      setTimeout(() => { stix.textContent = label; }, 2500);
    }
  });
  return [json, stix];
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
// unpriced > 0: some requests have no price, so the sum is only a lower bound ("co najmniej").
function costLine(seconds, cost, unpriced) {
  if (typeof cost !== "number") return `w ${seconds} s`;
  return `w ${seconds} s, koszt modelu ${unpriced > 0 ? "co najmniej " : ""}${USD.format(cost)}`;
}

// Scenario H: the API sets moderator_case only once the case is stored, so this is never said about
// a hand-off that did not happen. Same words as the Discord bot (prawdowid/discord_bot.py).
const MODERATOR_NOTE = "Zgłoszenie trafiło do kolejki moderatora";
// After "Usuń moje sprawdzenia" took the session's questions out of the moderator cases.
const DELETED_AND_WITHDRAWN = "Usunęliśmy sprawdzenia z tej sesji i wycofaliśmy zgłoszenia z kolejki moderatora.";

// Scenario F: what a model read from the image, above the claims. It is what was checked, never
// evidence. On a notice the limitations are already listed above it.
function imageSection(check, withLimits) {
  const img = check.image;
  if (!img?.text) return null;
  const exif = [img.taken_at ? `zrobiono ${img.taken_at}` : null, img.camera ? `aparat ${img.camera}` : null].filter(Boolean);
  return el("section", { className: "image-read" },
    el("h2", { className: "part", textContent: "Odczytany tekst" }),
    el("blockquote", { className: "read-text", textContent: img.text }),
    img.visible_date ? el("p", { className: "origin", textContent: `Data widoczna na obrazie: ${img.visible_date}` }) : null,
    exif.length ? el("p", { className: "origin", textContent: `Metadane EXIF: ${exif.join(", ")}` }) : null,
    withLimits && check.limitations?.length
      ? el("div", { className: "unknown" }, el("h3", { className: "unknown-title", textContent: "Ograniczenia" }),
          el("ul", {}, ...check.limitations.map((l) => el("li", { textContent: l }))))
      : null);
}

function moderatorNote(c) {
  return c ? el("p", { className: "note moderator", textContent: `${MODERATOR_NOTE} (sprawa ${c.id}).` }) : null;
}

function render(check, seconds) {
  const warning = incidentWarning(check.incident_matches);
  const moderator = moderatorNote(check.moderator_case);
  // Statuses other than "ok" are notices, never verdicts.
  if (check.status !== "ok") {
    const main = notice(NOTICE_TITLES[check.status] ?? "Brak oceny", check.message, NOT_A_VERDICT);
    const limits = check.limitations?.length
      ? el("ul", {}, ...check.limitations.map((l) => el("li", { textContent: l })))
      : null;
    const read = imageSection(check, false);
    if (!check.security_events?.length && !limits && !warning && !moderator && !read) return main;
    return el("div", {},
      check.security_events?.length ? notice("Polecenia dla modelu", SECURITY_NOTE_ONLY) : null,
      main, limits, read, warning, moderator);
  }
  const unchecked = check.unchecked_claims ?? [];
  if (!check.claims.length && !unchecked.length) {
    const empty = notice("Nie znaleźliśmy zdania do sprawdzenia",
      "Wklej fragment z konkretnym faktem, na przykład datą, liczbą albo nazwą instytucji.");
    return warning || moderator ? el("div", {}, empty, warning, moderator) : empty;
  }
  const events = check.security_events ?? [];
  return el("article", { className: "card" },
    events.some((e) => e.location !== "source") ? notice("Polecenia dla modelu", SECURITY_NOTE) : null,
    events.some((e) => e.location === "source") ? notice("Polecenia w źródle", SOURCE_SECURITY_NOTE) : null,
    el("div", { className: "card-head" },
      el("div", {},
        el("p", { className: "card-title" }, `Sprawdziliśmy ${plural(check.claims.length, "zdanie", "zdania", "zdań")} `,
          el("span", { className: "took", textContent: costLine(seconds, check.cost_usd, check.unpriced_requests) })),
        summary(check.claims)),
      el("div", { className: "card-actions" }, copyButton(check), ...exportButtons(check))),
    check.page ? pageNote(check.page) : null,
    imageSection(check, true),
    warning,
    ...check.claims.map(claimBlock),
    unchecked.length ? uncheckedList(unchecked) : null,
    moderator);
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
  [submit, ...chips, deleteSession, attachButton, removeImage].forEach((control) => control.setAttribute("aria-disabled", String(value)));
}

// Cleared first so the same message is announced again on a repeated attempt. `field` is marked
// invalid; an image error marks none, since the text box is not at fault.
function fieldError(message, field = input) {
  cancelAnimationFrame(errorFrame);
  formError.textContent = "";
  formError.hidden = !message;
  input.removeAttribute("aria-invalid");
  if (!message) return;
  field?.setAttribute("aria-invalid", "true");
  errorFrame = requestAnimationFrame(() => { formError.textContent = message; });
}

// Read in the browser as a data: URL, which the page's CSP allows as an image source; the API
// gets the base64 part. Nothing is uploaded until the check is sent.
function setImage(file) {
  if (busy) return;
  if (!IMAGE_TYPES.includes(file.type)) {
    fieldError("Przyjmujemy tylko obrazy PNG, JPEG i WebP.", null);
    return;
  }
  if (file.size > MAX_IMAGE_BYTES) {
    fieldError("Obraz jest za duży. Limit to 5 MB.", null);
    return;
  }
  const reader = new FileReader();
  reader.addEventListener("load", () => {
    const url = String(reader.result);
    image = { data: url.slice(url.indexOf(",") + 1), name: file.name || "obraz ze schowka" };
    previewImg.src = url;
    previewImg.alt = `Podgląd dodanego obrazu: ${image.name}`;
    previewName.textContent = image.name;
    preview.hidden = false;
    fieldError("");
    imageStatus.textContent = `Dodano obraz ${image.name}. Wyślij, a odczytamy z niego tekst i go sprawdzimy.`;
  });
  reader.addEventListener("error", () => fieldError("Nie udało się wczytać obrazu. Spróbuj innego pliku.", null));
  reader.readAsDataURL(file);
}

function clearImage() {
  image = null;
  preview.hidden = true;
  previewImg.removeAttribute("src");
  previewImg.alt = "";
  previewName.textContent = "";
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (busy) return;
  const text = input.value.trim();
  if ((!text && !image) || chars(text) > MAX_CHARS) {
    fieldError(text ? `Treść jest za długa. Limit to ${MAX_CHARS} znaków.` : "Wpisz tekst do sprawdzenia.");
    input.focus();
    return;
  }
  fieldError("");
  setBusy(true);
  const started = Date.now();
  const elapsed = () => Math.max(1, Math.round((Date.now() - started) / 1000));
  const where = "w Google Fact Check, EUvsDisinfo, na www.gov.pl i w wyszukiwarce ograniczonej do zaufanych stron. Może to potrwać kilkadziesiąt sekund.";
  const waiting = notice("Sprawdzamy", image ? `Odczytujemy tekst z obrazu, potem szukamy ${where}` : `Szukamy ${where}`);
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
      body: JSON.stringify(image ? { input: text, image: image.data } : { input: text }),
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
// A screenshot pasted into the box is attached; pasted text still goes in as text.
input.addEventListener("paste", (event) => {
  const file = [...(event.clipboardData?.files ?? [])].find((f) => f.type.startsWith("image/"));
  if (!file) return;
  if (!event.clipboardData.getData("text/plain")) event.preventDefault();
  setImage(file);
});
attachButton.addEventListener("click", () => {
  if (!busy) fileInput.click();
});
fileInput.addEventListener("change", () => {
  const [file] = fileInput.files;
  // Cleared, so choosing the same file again still fires "change".
  fileInput.value = "";
  if (file) setImage(file);
});
removeImage.addEventListener("click", () => {
  if (busy) return;
  clearImage();
  imageStatus.textContent = "Usunięto obraz.";
  attachButton.focus();
});
input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing && ENTER_SENDS.matches) {
    event.preventDefault();
    form.requestSubmit();
  }
});


// Demo session: the API issues an id on the first check; this tab sends it back and can delete it.
const SESSION_KEY = "prawdowid-session";
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
  deleteSession.hidden = false;
  sessionStatus.textContent = "";
}

deleteSession.addEventListener("click", async () => {
  const id = storedSession();
  // Not while a check runs: its response would bring the deleted session back.
  if (!id || busy) return;
  deleteSession.disabled = true;
  try {
    const resp = await fetch(`/api/sessions/${encodeURIComponent(id)}`, {
      method: "DELETE",
      signal: AbortSignal.timeout(10000),
    });
    if (!resp.ok) throw new Error(String(resp.status));
    // How many of the session's questions left the moderator cases: a case note in an earlier answer no longer holds.
    const { withdrawn } = await resp.json().catch(() => ({}));
    storeSession(null);
    deleteSession.hidden = true;
    input.focus();
    sessionStatus.textContent = withdrawn > 0 ? DELETED_AND_WITHDRAWN : "Usunęliśmy sprawdzenia z tej sesji.";
  } catch {
    sessionStatus.textContent = "Nie udało się usunąć sprawdzeń. Spróbuj ponownie za chwilę.";
  } finally {
    deleteSession.disabled = false;
  }
});

if (storedSession()) deleteSession.hidden = false;

chips.forEach((chip) => chip.addEventListener("click", () => {
  if (busy) return;
  // An example is checked on its own, not with an image added earlier.
  clearImage();
  input.value = chip.dataset.example;
  fieldError("");
  // The chips hide once a check starts, so keep keyboard focus in the box.
  input.focus();
  form.requestSubmit();
}));
