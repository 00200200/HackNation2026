"""Mask obvious personal data before text leaves the service, and the retention period.

Regex plus checksums, no NLP: e-mail addresses, bank account numbers (Polish NRB by shape, other IBANs
mod-97 checked), card numbers (13-19 digits, Luhn checked), PESEL numbers with a valid checksum and
phone numbers written as "+48 600 100 200" or "600-100-200". Plain digit runs such as "600100200"
or "600 100 200" stay: in a claim they are usually amounts. Names and addresses are not detected.

Presidio (checked 2026-11-21, presidio-analyzer 2.2.366) was not taken: its only Polish recognizer
is PESEL, which this module already covers, and it pulls in spaCy and a language model. Where the
masking is applied: docs/privacy.md.
"""

import re

# One retention period for everything we keep: check log records (prawdowid/checklog.py) and pages
# in the source store (prawdowid/cache.py, `delete_after`). The web page text
# (frontend/public/index.html, "do 30 dni") repeats it: change both.
RETENTION_DAYS = 30

EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
ACCOUNT = re.compile(r"\b(?:PL ?)?\d{2}(?: ?\d{4}){6}\b")
IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,3})?\b")
# Groups of four ("4111 1111 1111 1111") or one run; amounts are grouped in threes and never match.
CARD = re.compile(r"\b\d{4}(?:[ -]\d{4}){2,3}(?:[ -]\d{1,3})?\b|\b\d{13,19}\b")
PHONE = re.compile(r"\+48[ -]?\d{3}[ -]?\d{3}[ -]?\d{3}\b|\b\d{3}-\d{3}-\d{3}\b")
ELEVEN_DIGITS = re.compile(r"\b\d{11}\b")
PESEL_WEIGHTS = (1, 3, 7, 9, 1, 3, 7, 9, 1, 3)


def is_pesel(digits: str) -> bool:
    total = sum(int(d) * w for d, w in zip(digits, PESEL_WEIGHTS))
    return (10 - total % 10) % 10 == int(digits[10])


def is_luhn(digits: str) -> bool:
    total = 0
    for i, d in enumerate(reversed(digits)):
        n = int(d) * (2 if i % 2 else 1)
        total += n - 9 if n > 9 else n
    return total % 10 == 0


def is_iban(text: str) -> bool:
    s = text.replace(" ", "")
    return int("".join(str(int(c, 36)) for c in s[4:] + s[:4])) % 97 == 1


def _digits(text: str) -> str:
    return re.sub(r"\D", "", text)


def _masker(valid, placeholder: str):
    """re.sub callback: mask a valid match. The optional last group may be a separate token
    (a CVV, a currency), so when the whole match fails it is retried without that group."""

    def sub(m: re.Match) -> str:
        s = m.group()
        if valid(s):
            return placeholder
        head, sep, tail = re.fullmatch(r"(.*?)([ -]?)([^ -]*)", s).groups()
        return placeholder + sep + tail if sep and valid(head) else s

    return sub


def mask_personal_data(text: str) -> str:
    # Account numbers first: they contain digit runs the other patterns would match.
    text = ACCOUNT.sub("[numer konta]", text)
    text = IBAN.sub(_masker(is_iban, "[numer konta]"), text)
    text = EMAIL.sub("[e-mail]", text)
    text = PHONE.sub("[telefon]", text)
    # PESEL before cards: 11 digits are too short for a card, so the order only saves work.
    text = ELEVEN_DIGITS.sub(
        lambda m: "[PESEL]" if is_pesel(m.group()) else m.group(), text
    )
    # ponytail: a 13+ digit run that passes Luhn (1 in 10) is masked even if it is an amount;
    # amounts that large are rare in claims and usually written in groups of three.
    return CARD.sub(_masker(lambda s: is_luhn(_digits(s)), "[numer karty]"), text)
