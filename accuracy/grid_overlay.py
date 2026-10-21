from pathlib import Path
import sys

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]


def main(path: Path) -> None:
    image = Image.open(path).convert("RGB")
    draw = ImageDraw.Draw(image, "RGBA")
    width, height = image.size
    font = ImageFont.load_default(size=18)
    for step in range(1, 10):
        x = width * step / 10
        y = height * step / 10
        draw.line([(x, 0), (x, height)], fill=(255, 0, 180, 120), width=2)
        draw.line([(0, y), (width, y)], fill=(0, 255, 200, 120), width=2)
        draw.text((x + 5, 8), f"{step / 10:.1f}", fill=(255, 255, 255, 230), font=font)
        draw.text((8, y + 3), f"{step / 10:.1f}", fill=(255, 255, 255, 230), font=font)
    out = path.with_name(path.stem + "_grid.jpg")
    image.save(out, quality=92)
    print(out)


if __name__ == "__main__":
    main(Path(sys.argv[1]))
