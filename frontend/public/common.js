// Shared by the check page (app.js) and the source list (zrodla.js), loaded before either of them.
// Source types from the corpus catalogue and the web-search allowlist; anything else is shown as sent.
const SOURCE_TYPES = {
  official: "źródło oficjalne",
  primary: "źródło pierwotne",
  fact_checker: "serwis fact-checkingowy",
  fact_check: "serwis fact-checkingowy",
  incident_base: "baza incydentów dezinformacji",
  disinfo_database: "baza znanych narracji dezinformacyjnych",
  news: "serwis informacyjny",
};
const PLURAL = new Intl.PluralRules("pl-PL");

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  Object.assign(node, attrs);
  node.append(...children.filter((c) => c !== null && c !== undefined && c !== false));
  return node;
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
