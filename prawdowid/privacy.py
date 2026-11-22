"""Mask obvious personal data before text leaves the service, and the retention period.

Regex plus checksums, no NLP: e-mail addresses, bank account numbers (Polish NRB by shape, other IBANs
mod-97 checked), card numbers (13-19 digits, Luhn checked), PESEL numbers with a valid checksum, ID
card numbers (3 capital letters and 6 digits, check digit), passport numbers (2 capital letters and 7
digits) and phone numbers: any nine digits after a country code ("+48", "0048", "(48)"), a dashed
number (600-100-200), an area code in brackets, or a bare nine-digit number that starts with a mobile
prefix or follows "tel.". A bare number stays when it looks like an amount or an id: a currency next
to it ("500 000 000 zł"), a count behind it ("512 345 678 osób"), 000 at the end, a REGON label or a
URL around it; a label such as "tel." overrides most of these, never a currency. Names and addresses
are not detected, on purpose: the name of a public figure is part of the question and is needed to
find evidence.

No library fits (checked 2026-11-22). Presidio (presidio-analyzer 2.2.366) has PESEL as its only Polish
recognizer (an ID card recognizer is an open pull request) and pulls in spaCy and a language model.
python-stdnum 2.2 has `pl` modules for NIP, PESEL and REGON only. phonenumbers 9.0.44 reports
"123456789 zł" and "500 000 000 zł" as valid Polish numbers, which is what a mask must not do.
Where the masking is applied, what stays and what is not detected: docs/privacy.md.
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
# Nine digits grouped 3-3-3, 3-2-2-2 or, for a landline, 2-3-2-2 (the area code may be in brackets),
# or written as one run. A space can be a no-break space.
_D2, _D3 = r"\d{2}", r"\d{3}"
_SEP = r"[ \N{NO-BREAK SPACE}-]"
_S = _SEP + "?"
_NUMBER = (
    rf"{_D3}{_S}{_D3}{_S}{_D3}|{_D3}{_S}{_D2}{_S}{_D2}{_S}{_D2}"
    rf"|\(?{_D2}\)?{_S}{_D3}{_S}{_D2}{_S}{_D2}"
)
# After a country code any nine digits are a phone, whatever stands next to them: "24/7 +48 600 100 200".
PHONE_WITH_CODE = re.compile(rf"(?:\(\+?48\)|\+48|(?<!\d)0048){_S}(?:{_NUMBER})(?!\d)")
# Without one the number must stand alone: not the tail of a longer number ("1 600 123 456 zł"), not
# the head of one ("600 123 456 789", see MORE_DIGITS), not a decimal ("600123456.50"), not part of an
# id ("gus-532015686e").
PHONE = re.compile(rf"(?<!\w)(?<!\d{_SEP})(?P<number>{_NUMBER})(?!\w|[.,]\d)")
# Another group of digits behind a number: it may be the head of a longer number, unless a label says
# it is a phone ("tel. 600123456 44051401359"). Checked in `_mask_phone`, not in PHONE, so that a
# labelled phone is recognised whatever stands behind it.
MORE_DIGITS = re.compile(rf"{_SEP}\d{{3}}")
# The run of three-digit groups a labelled number may continue with ("226 000 000 000 sztuk").
DIGIT_GROUPS = re.compile(rf"(?:{_SEP}\d{{3}})+")
# 600-100-200 is a phone wherever it stands, next to other numbers too (the one bare format that was
# masked before).
DASHED_PHONE = re.compile(r"\b\d{3}-\d{3}-\d{3}\b")
# First digits of Polish mobile numbers: the 13 mobile prefixes of the numbering plan (Dz.U. 2024 poz.
# 1862). libphonenumber 9.0.44 (PL metadata) lists the same plus the range 21x, which the plan assigns
# to machine-to-machine services, so it is left out. Landline area codes are left out too: a landline
# is masked after a country code, in brackets or after a label, because "12 345 67 89" alone is not a phone.
MOBILE = re.compile(r"(?:45|5[0137]|6[069]|7[2389]|88)\d{7}")
PHONE_LABEL = re.compile(
    r"\b(?:tel|telefon\w*|kom|komórk\w*|fax|faks|phone|mobile|sms|whatsapp)\W{0,3}"
    r"(?:(?:nr|numer)\W{0,3})?$",
    re.IGNORECASE,
)
# A REGON can start like a mobile number; a URL carries ids.
REGON_LABEL = re.compile(r"\bregon\W{0,3}(?:(?:nr|numer)\W{0,3})?$", re.IGNORECASE)
URL_TAIL = re.compile(r"(?:://|\bwww\.)\S*$")
# Money: a currency in front of the number, or a currency or a magnitude word behind it. A label
# ("tel.") does not beat it. A count ("osób") only rules out a bare number with no label: "tel. 600 123
# 456 osoby, która dzwoniła" is still a phone.
CURRENCY_BEFORE = re.compile(r"(?:\b(?:pln|eur|usd|gbp|chf)|[€$£])\s*$", re.IGNORECASE)
MONEY_UNIT = re.compile(
    r"\s*(?:(?:zł|zl|pln|eur|euro|usd|gbp|chf|dol|mln|mld|tys|proc)\b|złot|dolar|[%€$£])",
    re.IGNORECASE,
)
COUNT_UNIT = re.compile(
    r"\s*(?:osób|osoby|ludzi|mieszkańców|obywateli|sztuk|szt)\b", re.IGNORECASE
)
# Capitals as printed: "dla 100000 osób" is not an ID card. A currency code and a space are skipped
# because "PLN 123456" passes the check digit; glued ("PLN123456") it is a card number as any other.
ID_CARD = re.compile(r"\b(?!(?:PLN|EUR|USD|GBP|CHF) )[A-Z]{3} ?\d{6}\b")
# Shape only, no check digit: UNCONFIRMED, two unofficial sources disagree on where it sits (3rd or last
# character). A space is not allowed, "nr 1234567" is an ordinary phrase (lower case never matches either).
# A product code is public and is not a card: a label in front of it, or a URL around it.
PRODUCT_LABEL = re.compile(
    r"\b(?:ean|gtin|upc|sku|kod\w*|numer\w*|nr|partii|lot|id)\W{0,3}"
    r"(?:(?:kreskow\w*|produktu|partii|seryjn\w*|katalogow\w*)\W{0,3})?$",
    re.IGNORECASE,
)
PASSPORT = re.compile(r"\b[A-Z]{2}\d{7}\b")
# Digit boundaries, not \b: "PESEL44051401359" has no word boundary before the digits.
ELEVEN_DIGITS = re.compile(r"(?<!\d)\d{11}(?!\d)")
REPR_ESCAPE = re.compile(r"\\[nrt]")
PESEL_WEIGHTS = (1, 3, 7, 9, 1, 3, 7, 9, 1, 3)
# Weighted sum of the 9 characters (A=10 ... Z=35) is 0 mod 10; the 9 sits on the check digit.
ID_CARD_WEIGHTS = (7, 3, 1, 9, 7, 3, 1, 7, 3)


# ponytail: an ordinary 11-digit number passes the PESEL checksum 1 time in 10 and is masked too;
# such numbers are rare in claims.
def is_pesel(digits: str) -> bool:
    total = sum(int(d) * w for d, w in zip(digits, PESEL_WEIGHTS))
    return (10 - total % 10) % 10 == int(digits[10])


def is_id_card(text: str) -> bool:
    chars = text.replace(" ", "")
    return sum(int(c, 36) * w for c, w in zip(chars, ID_CARD_WEIGHTS)) % 10 == 0


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


def _mask_phone(m: re.Match) -> str:
    """A bare number (no country code, not dashed) is a phone when its area code is in brackets, it
    follows a label ("tel.") or it starts with a mobile prefix. It is an amount or an id, not a
    phone, with a currency or "mln" next to it, or with 000 at the end and a count ("osób") behind
    it ("telefonów 226 000 000 sztuk"). Without a label also with either of those two alone, a REGON
    label in front or a URL around it."""
    number = m["number"]
    before = m.string[max(m.start() - 200, 0) : m.start()]
    if MORE_DIGITS.match(m.string, m.end()) and not PHONE_LABEL.search(before):
        return m.group()
    if number.startswith("("):
        return "[telefon]"
    digits = _digits(number)
    # A URL is judged by its whole token: its scheme can be further back than `before` reaches.
    head = m.string[: m.start()]
    token = "" if not head or head[-1].isspace() else head.rsplit(None, 1)[-1]
    # A unit after more three-digit groups still makes an amount or a count ("telefonów 226 000 000
    # 000 sztuk"), so look for it behind the whole run, not right after the nine matched digits.
    groups = DIGIT_GROUPS.match(m.string, m.end())
    end = groups.end() if groups else m.end()
    count = COUNT_UNIT.match(m.string, end)
    round_number = digits.endswith("000") or bool(
        groups and groups.group().endswith("000")
    )
    mobile = (
        MOBILE.fullmatch(digits)
        and not (round_number or count)
        and not (REGON_LABEL.search(before) or URL_TAIL.search(token))
    )
    money = CURRENCY_BEFORE.search(before) or MONEY_UNIT.match(m.string, end)
    if (PHONE_LABEL.search(before) or mobile) and not (
        money or (round_number and count)
    ):
        return "[telefon]"
    return m.group()


def _mask_id_card(m: re.Match) -> str:
    # "NFZ 100000 zł" passes the check digit too: an acronym, a space and a unit behind the digits
    # make an amount. A code with the letters glued to the digits ("ABA300000") is never one.
    unit = MONEY_UNIT.match(m.string, m.end()) or COUNT_UNIT.match(m.string, m.end())
    if is_id_card(m.group()) and not (unit and " " in m.group()):
        return "[numer dowodu]"
    return m.group()


def mask_personal_data(text: str) -> str:
    # Account numbers first: they contain digit runs the other patterns would match.
    text = ACCOUNT.sub("[numer konta]", text)
    text = IBAN.sub(_masker(is_iban, "[numer konta]"), text)
    text = EMAIL.sub("[e-mail]", text)
    text = PHONE_WITH_CODE.sub("[telefon]", text)
    text = DASHED_PHONE.sub("[telefon]", text)
    text = PHONE.sub(_mask_phone, text)
    # PESEL before cards: 11 digits are too short for a card, so the order only saves work.
    text = ELEVEN_DIGITS.sub(
        lambda m: "[PESEL]" if is_pesel(m.group()) else m.group(), text
    )
    # ponytail: a random 3-letters-6-digits code passes the check digit 1 time in 10 and is masked too.
    text = ID_CARD.sub(_mask_id_card, text)
    text = PASSPORT.sub("[numer paszportu]", text)
    # ponytail: a 13+ digit run that passes Luhn (1 in 10) is masked even if it is an amount;
    # amounts that large are rare in claims and usually written in groups of three. A product code
    # (label, URL or EAN-13 check digit) stays: `_mask_card`.
    return CARD.sub(_mask_card, text)


def _is_card(text: str) -> bool:
    digits = _digits(text)
    return 13 <= len(digits) <= 19 and is_luhn(digits)


def is_gtin13(digits: str) -> bool:
    """GS1 check digit of an EAN-13: weights 1, 3, 1, 3 ... over the first 12 digits."""
    if len(digits) != 13:
        return False
    total = sum(int(d) * (3 if i % 2 else 1) for i, d in enumerate(digits[:12]))
    return (10 - total % 10) % 10 == int(digits[12])


_mask_luhn = _masker(_is_card, "[numer karty]")


def _mask_card(m: re.Match) -> str:
    # ponytail: a 13-digit run with a valid EAN check digit is a product code, not a card (13-digit
    # cards are nearly extinct); so is any number after a product label or inside a URL.
    before = m.string[max(m.start() - 60, 0) : m.start()]
    code = m.group()
    if PRODUCT_LABEL.search(before) or URL_TAIL.search(before) or is_gtin13(code):
        return code
    return _mask_luhn(m)


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
