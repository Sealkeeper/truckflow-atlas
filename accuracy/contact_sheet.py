from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
FRAMES = ROOT / "assets" / "frames"
OUT = ROOT / "accuracy" / "contact_sheet.jpg"

times = [5, 300, 600, 900, 1200, 1500, 1800, 2100, 2400, 2600]
thumbs = []
for camera in ("north", "south"):
    for t in times:
        path = FRAMES / f"{camera}_{t}.jpg"
        image = Image.open(path).convert("RGB")
        image.thumbnail((480, 360))
        canvas = Image.new("RGB", (480, 390), "#0c151d")
        canvas.paste(image, ((480 - image.width) // 2, 30))
        draw = ImageDraw.Draw(canvas)
        draw.text((12, 8), f"{camera.upper()}  t={t}s  {t // 60:02d}:{t % 60:02d}", fill="#57f2d0")
        thumbs.append(canvas)

cols = 4
rows = (len(thumbs) + cols - 1) // cols
sheet = Image.new("RGB", (cols * 490, rows * 400), "#081018")
for index, thumb in enumerate(thumbs):
    sheet.paste(thumb, ((index % cols) * 490, (index // cols) * 400))
sheet.save(OUT, quality=92)
print(OUT)
