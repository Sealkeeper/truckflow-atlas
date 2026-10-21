"""Render genuine input frames and the cached model's own boxes, never invented labels."""
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent


def font(size):
    candidate = Path("C:/Windows/Fonts/arial.ttf")
    return ImageFont.truetype(str(candidate), size) if candidate.exists() else ImageFont.load_default()


def main():
    metrics = json.loads((HERE / "metrics.json").read_text(encoding="utf-8"))
    manifest = json.loads((HERE / "manifest.json").read_text(encoding="utf-8"))
    truth = {(r["camera"], r["time_s"]): r["truth"] for r in metrics["rows"]}
    width, image_height, panel_height = 640, 480, 550
    canvas = Image.new("RGB", (width * 3, 100 + panel_height * 3), "#101923")
    draw = ImageDraw.Draw(canvas)
    draw.text((20, 13), "EVENT LEDGER: 3 chronological frames per VLM call", font=font(27), fill="white")
    draw.text((20, 53), "Boxes / IDs = raw model output, not human labels. Truth only at the 3 user-reviewed times.", font=font(19), fill="#b3c8d8")
    colors = ["#70e2ff", "#ffd469", "#d5a0ff", "#78efb3", "#ff9ca9"]
    for row, window in enumerate(manifest["windows"]):
        raw = json.loads((HERE / "raw" / f"{window['name']}.json").read_text(encoding="utf-8"))
        for col, snapshot in enumerate(raw["parsed"]["snapshots"]):
            image = Image.open(HERE / window["images"][col]["path"]).convert("RGB").resize((width, image_height))
            marking = ImageDraw.Draw(image)
            for index, vehicle in enumerate(snapshot["visible_vehicles"]):
                box = vehicle["bbox"]
                coords = [int(box[0] * width), int(box[1] * image_height), int(box[2] * width), int(box[3] * image_height)]
                color = colors[index % len(colors)]
                marking.rectangle(coords, outline=color, width=3)
                tx, ty = coords[0], max(0, coords[1] - 23)
                marking.rectangle((tx, ty, tx + 43, ty + 23), fill="#101923")
                marking.text((tx + 2, ty), vehicle["id"], font=font(19), fill=color)
            x, y = col * width, 100 + row * panel_height
            canvas.paste(image, (x, y))
            known = truth.get((window["camera"], snapshot["time_s"]))
            count = len(snapshot["visible_vehicles"])
            status = f"USER TRUTH={known}" if known is not None else "truth not labeled"
            label_color = "#ff8c8c" if known is not None and known != count else "#d2edfa"
            draw.text((x + 10, y + image_height + 7), f"{window['camera']} t={int(snapshot['time_s'])}s | predicted={count} | {status}", font=font(18), fill=label_color)
            draw.text((x + 10, y + image_height + 34), "ledger review=false; automatic gate accepts", font=font(17), fill="#b3c8d8")
    output = HERE / "evidence_contact.jpg"
    canvas.save(output, quality=94)
    print(output)


if __name__ == "__main__":
    main()
