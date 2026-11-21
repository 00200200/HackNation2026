"""Mask obvious personal data before text leaves the service, and the retention period.

Regex plus checksums, no NLP: e-mail addresses, bank account numbers (Polish NRB by shape, other IBANs
mod-97 checked), card numbers (13-19 digits, Luhn checked), PESEL numbers with a valid checksum and
phone numbers written as "+48 600 100 200" or "600-100-200". Plain digit runs such as "600100200"
or "600 100 200" stay: in a claim they are usually amounts. Names and addresses are not detected.

Presidio (checked 2026-11-21, presidio-analyzer 2.2.366) was not taken: its only Polish recognizer
is PESEL, which this module already covers, and it pulls in spaCy and a language model. Where the
masking is applied: docs/privacy.md.
"""

import logging
import re
import traceback

# One retention period for everything we keep: check log records (prawdowid/checklog.py), the source
# cache corpus/docs.jsonl and pages in the source store (prawdowid/cache.py, `delete_after`). The web page text
# (frontend/public/index.html, "do 30 dni") repeats it: change both.
RETENTION_DAYS = 30

EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
ACCOUNT = re.compile(r"\b(?:PL ?)?\d{2}(?: ?\d{4}){6}\b")
IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,3})?\b")
# Groups of four ("4111 1111 1111 1111") or one run; amounts are grouped in threes and never match.
CARD = re.compile(r"\b\d{4}(?:[ -]\d{4}){2,3}(?:[ -]\d{1,3})?\b|\b\d{13,19}\b")
PHONE = re.compile(r"\+48[ -]?\d{3}[ -]?\d{3}[ -]?\d{3}\b|\b\d{3}-\d{3}-\d{3}\b")
# Digit boundaries, not \b: "PESEL44051401359" has no word boundary before the digits.
ELEVEN_DIGITS = re.compile(r"(?<!\d)\d{11}(?!\d)")
REPR_ESCAPE = re.compile(r"\\[nrt]")
PESEL_WEIGHTS = (1, 3, 7, 9, 1, 3, 7, 9, 1, 3)


# ponytail: an ordinary 11-digit number passes the PESEL checksum 1 time in 10 and is masked too;
# such numbers are rare in claims.
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
    # IBANs are 15-34 characters; the length check stops a stripped match passing by chance.
    return (
        15 <= len(s) <= 34
        and int("".join(str(int(c, 36)) for c in s[4:] + s[:4])) % 97 == 1
    )


def _digits(text: str) -> str:
    return re.sub(r"\D", "", text)


def _masker(valid, placeholder: str):
    """re.sub callback: mask a valid match. Words after the number (a CVV, a currency, a bank name)
    can match as more groups, so when the whole match fails, trailing tokens are dropped one by one
    and the longest valid head is masked."""

    def sub(m: re.Match) -> str:
        s = m.group()
        head = s
        while head:
            if valid(head):
                return placeholder + s[len(head) :]
            head = head[: max(head.rfind(" "), head.rfind("-"), 0)]
        return s

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
    return CARD.sub(_masker(_is_card, "[numer karty]"), text)


def _is_card(text: str) -> bool:
    digits = _digits(text)
    return 13 <= len(digits) <= 19 and is_luhn(digits)


class MaskingFilter(logging.Filter):
    """Mask every log record, the traceback included: an unexpected exception can carry raw
    user text (a link with an e-mail in its query string) in its message."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except (TypeError, ValueError, KeyError):
            # A broken log call: keep its text, masked, instead of failing the request.
            args = record.args
            values = args.values() if isinstance(args, dict) else args or ()
            message = " ".join(map(str, (record.msg, *values)))
        # A repr (%r, a list arg) writes a newline as backslash-n, and the n would hide the digits
        # after it from the \b patterns; in a log line a space reads the same.
        record.msg = mask_personal_data(REPR_ESCAPE.sub(" ", message))
        record.args = None
        if record.exc_info:
            text = "".join(traceback.format_exception(*record.exc_info)).rstrip("\n")
            record.exc_text = mask_personal_data(REPR_ESCAPE.sub(" ", text))
            record.exc_info = None
        return True
