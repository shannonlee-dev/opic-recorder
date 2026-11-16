"""Package the approved source artwork as a Windows ICO; requires Pillow."""

from pathlib import Path

from PIL import Image

folder = Path(__file__).resolve().parents[1] / "assets"
with Image.open(folder / "speaking-recorder.png") as image:
    image.save(folder / "speaking-recorder.ico", sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
