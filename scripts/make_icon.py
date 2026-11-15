"""Rebuild the code-drawn app icon. Development only: requires Pillow."""

from pathlib import Path

from PIL import Image, ImageDraw

SCALE = 4
image = Image.new("RGBA", (256 * SCALE, 256 * SCALE))
draw = ImageDraw.Draw(image)


def box(coords):
    return tuple(int(n * SCALE) for n in coords)


def rounded(coords, radius, fill):
    draw.rounded_rectangle(box(coords), radius=radius * SCALE, fill=fill)


# Large silhouette, no lettering: readable at desktop and title-bar sizes.
rounded((12, 12, 244, 244), 54, "#183a77")
rounded((23, 23, 233, 233), 44, "#2459cf")
rounded((88, 45, 154, 146), 33, "#ffffff")
for y in (70, 86, 102):
    rounded((103, y, 139, y + 6), 3, "#a9c7ff")
draw.arc(box((68, 96, 174, 174)), 0, 180, fill="white", width=12 * SCALE)
rounded((68, 102, 80, 137), 6, "white")
rounded((162, 102, 174, 137), 6, "white")
rounded((115, 168, 127, 195), 5, "white")
rounded((92, 192, 150, 204), 6, "white")
draw.ellipse(box((165, 166, 223, 224)), fill="#183a77")
draw.ellipse(box((173, 174, 215, 216)), fill="#ff4646")
image = image.resize((256, 256), Image.Resampling.LANCZOS)
folder = Path(__file__).resolve().parents[1] / "assets"
folder.mkdir(exist_ok=True)
image.save(folder / "opic-recorder.png")
image.save(folder / "opic-recorder.ico", sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
