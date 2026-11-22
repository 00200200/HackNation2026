"""Builds the scenario F eval images: synthetic screenshots of posts, each with text and a date.

Every account, name and post here is made up; no real person's data. The claims repeat facts the
eval set already labels (see the F cases in evals/cases.jsonl). The font is the site's own Figtree
(SIL OFL), so the images rebuild the same on any machine with Pillow:

    uv run python evals/fixtures/make_images.py
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent.parent
FONT = ROOT / "frontend" / "public" / "fonts" / "Figtree.woff2"
OUT = Path(__file__).resolve().parent / "images"
WIDTH = 900
MARGIN = 48

POSTS = {
    # A social media post, true claim.
    "F01.png": {
        "style": "post",
        "name": "Przykładowe Konto",
        "handle": "@przykladowe_konto",
        "date": "3 listopada 2026, 09:15",
        "body": "Przypominam wszystkim: Polska jest członkiem NATO od 12 marca 1999 "
        "roku. Warto o tym pamiętać.",
    },
    # A social media post, false claim.
    "F02.png": {
        "style": "post",
        "name": "Wiadomości z Osiedla",
        "handle": "@wiadomosci_z_osiedla",
        "date": "22 października 2026",
        "body": "Ważne: w Polsce w ogóle nie przyjmuje się już wniosków o azyl. "
        "Przekażcie dalej!",
    },
    # A messenger screenshot with a relative date, true claim.
    "F03.png": {
        "style": "chat",
        "name": "Grupa Sąsiedzka",
        "handle": "",
        "date": "wczoraj, 19:42",
        "body": "Polska jest w strefie Schengen od 21 grudnia 2007 roku. "
        "Pamiętajcie o tym przed wyjazdem.",
    },
}


def font(size: int, weight: int) -> ImageFont.FreeTypeFont:
    face = ImageFont.truetype(str(FONT), size)
    face.set_variation_by_axes([weight])
    return face


def wrap(text: str, face: ImageFont.FreeTypeFont, width: int) -> list[str]:
    lines, line = [], ""
    for word in text.split():
        candidate = f"{line} {word}".strip()
        if line and face.getlength(candidate) > width:
            lines.append(line)
            line = word
        else:
            line = candidate
    return lines + [line]


def render(post: dict) -> Image.Image:
    name, small, body = font(30, 700), font(24, 400), font(34, 400)
    lines = wrap(post["body"], body, WIDTH - 2 * MARGIN - 40)
    height = 230 + 48 * len(lines) + 80
    chat = post["style"] == "chat"
    image = Image.new("RGB", (WIDTH, height), "#e9edf1" if chat else "#f0f2f5")
    draw = ImageDraw.Draw(image)
    if chat:
        draw.rectangle((0, 0, WIDTH, 96), fill="#2f6f5e")
        draw.text((MARGIN, 30), post["name"], font=name, fill="#ffffff")
        draw.text((MARGIN, 130), post["date"], font=small, fill="#5b6570")
        top = 170
        bubble = (MARGIN, top, WIDTH - MARGIN, top + 40 + 48 * len(lines))
        draw.rounded_rectangle(bubble, radius=22, fill="#ffffff")
        x, y = MARGIN + 20, top + 18
    else:
        draw.rounded_rectangle(
            (24, 24, WIDTH - 24, height - 24), radius=20, fill="#ffffff"
        )
        draw.ellipse((MARGIN, 48, MARGIN + 72, 120), fill="#8a5a9e")
        initials = "".join(part[0] for part in post["name"].split()[:2])
        draw.text((MARGIN + 36, 84), initials, font=small, fill="#ffffff", anchor="mm")
        draw.text((MARGIN + 92, 50), post["name"], font=name, fill="#1c1e21")
        draw.text(
            (MARGIN + 92, 88),
            f"{post['handle']} · {post['date']}",
            font=small,
            fill="#65676b",
        )
        x, y = MARGIN, 160
    for line in lines:
        draw.text((x, y), line, font=body, fill="#1c1e21")
        y += 48
    if not chat:
        draw.text(
            (MARGIN, height - 80),
            "Lubię to · Komentarz · Udostępnij",
            font=small,
            fill="#65676b",
        )
    return image


def main() -> None:
    OUT.mkdir(exist_ok=True)
    for filename, post in POSTS.items():
        render(post).save(OUT / filename, optimize=True)
        print(OUT / filename)


if __name__ == "__main__":
    main()
