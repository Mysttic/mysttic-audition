"""Ikona Mysttic Audition: jeden opis kształtów, z którego powstają wszystkie pliki.

    .venv/Scripts/python.exe tools/make_icons.py

Tworzy brand/icon.svg (źródło do README i strony), static/icon.ico (okno i pasek
zadań, rozmiary od 16 do 256 px) i static/icon.png (favicon). Potrzebuje Pillow
z requirements-dev.txt.

Rysunek: przebieg fali z pięciu słupków na niebieskim gradiencie aplikacji,
środkowy słupek w kolorze wyróżnienia wyników wyszukiwania.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageColor, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
GRID = 512  # współrzędne opisu
RADIUS = 112  # zaokrąglenie tła, jak w ikonach innych projektów Mysttic
TOP, BOTTOM = "#5AA9FF", "#2F6FB5"  # gradient tła: akcent aplikacji i kolor bieżącego słowa
BAR, HIGHLIGHT = "#FFFFFF", "#F5C542"
BAR_WIDTH, BAR_GAP = 56, 30
HEIGHTS = (150, 268, 348, 236, 132)
ICO_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def bars() -> list[tuple[float, float, float, float, str]]:
    """Słupki jako (x0, y0, x1, y1, kolor) w siatce 512 px, wyśrodkowane."""
    total = len(HEIGHTS) * BAR_WIDTH + (len(HEIGHTS) - 1) * BAR_GAP
    x = (GRID - total) / 2
    out = []
    for i, height in enumerate(HEIGHTS):
        color = HIGHLIGHT if i == len(HEIGHTS) // 2 else BAR
        out.append((x, (GRID - height) / 2, x + BAR_WIDTH, (GRID + height) / 2, color))
        x += BAR_WIDTH + BAR_GAP
    return out


def svg() -> str:
    rects = "\n".join(
        f'  <rect x="{x0:g}" y="{y0:g}" width="{x1 - x0:g}" height="{y1 - y0:g}" '
        f'rx="{BAR_WIDTH / 2:g}" fill="{color}"/>'
        for x0, y0, x1, y1, color in bars())
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {GRID} {GRID}" width="{GRID}" height="{GRID}" role="img" aria-label="Mysttic Audition">
  <defs>
    <linearGradient id="tlo" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="{TOP}"/>
      <stop offset="1" stop-color="{BOTTOM}"/>
    </linearGradient>
  </defs>
  <rect width="{GRID}" height="{GRID}" rx="{RADIUS}" ry="{RADIUS}" fill="url(#tlo)"/>
{rects}
</svg>
"""


def render(size: int) -> Image.Image:
    """Rysunek w 8-krotnym nadpróbkowaniu, zmniejszony filtrem Lanczosa: gładkie krawędzie także w 16 px."""
    side = size * 8
    scale = side / GRID
    top, bottom = ImageColor.getrgb(TOP), ImageColor.getrgb(BOTTOM)
    column = Image.new("RGB", (1, side))
    column.putdata([tuple(round(a + (b - a) * y / (side - 1)) for a, b in zip(top, bottom)) for y in range(side)])
    mask = Image.new("L", (side, side), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, side - 1, side - 1), radius=RADIUS * scale, fill=255)
    image = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    image.paste(column.resize((side, side)), (0, 0), mask)
    draw = ImageDraw.Draw(image)
    for x0, y0, x1, y1, color in bars():
        draw.rounded_rectangle((x0 * scale, y0 * scale, x1 * scale, y1 * scale),
                               radius=BAR_WIDTH / 2 * scale, fill=color)
    return image.resize((size, size), Image.LANCZOS)


def main() -> None:
    (ROOT / "brand").mkdir(exist_ok=True)
    (ROOT / "brand" / "icon.svg").write_text(svg(), "utf-8")
    images = [render(size) for size in ICO_SIZES]
    images[-1].save(ROOT / "static" / "icon.ico", sizes=[(s, s) for s in ICO_SIZES], append_images=images[:-1])
    images[-1].save(ROOT / "static" / "icon.png")
    print("brand/icon.svg, static/icon.ico, static/icon.png")


if __name__ == "__main__":
    main()
