"""Mask obvious personal data before text leaves the service (search queries, logs).

Regex only: e-mail addresses, bank account numbers (NRB/IBAN), PESEL numbers with a valid
checksum and phone numbers written as "+48 600 100 200" or "600-100-200". Plain digit runs such as
"600100200" or "600 100 200" stay: in a claim they are usually amounts. Names and addresses are
not detected; #17 owns the rest of privacy.
"""

import re

EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
ACCOUNT = re.compile(r"\b(?:PL ?)?\d{2}(?: ?\d{4}){6}\b")
PHONE = re.compile(r"\+48[ -]?\d{3}[ -]?\d{3}[ -]?\d{3}\b|\b\d{3}-\d{3}-\d{3}\b")
ELEVEN_DIGITS = re.compile(r"\b\d{11}\b")
PESEL_WEIGHTS = (1, 3, 7, 9, 1, 3, 7, 9, 1, 3)


def is_pesel(digits: str) -> bool:
    total = sum(int(d) * w for d, w in zip(digits, PESEL_WEIGHTS))
    return (10 - total % 10) % 10 == int(digits[10])


def mask_personal_data(text: str) -> str:
    # Account numbers first: they contain digit runs the other patterns would match.
    text = ACCOUNT.sub("[numer konta]", text)
    text = EMAIL.sub("[e-mail]", text)
    text = PHONE.sub("[telefon]", text)
    return ELEVEN_DIGITS.sub(
        lambda m: "[PESEL]" if is_pesel(m.group()) else m.group(), text
    )
