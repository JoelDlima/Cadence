from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

WIDTH, HEIGHT = 1600, 1000
INK = "#0B1220"
BLUE = "#3395FF"
MUTED = "#94A3B8"
WHITE = "#FFFFFF"
FONT_PATH = Path("C:/Windows/Fonts/arial.ttf")
FONT_BOLD_PATH = Path("C:/Windows/Fonts/arialbd.ttf")
OUT = Path(__file__).resolve().parents[1] / "docs" / "Cadence-architecture.png"


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT_BOLD_PATH if bold else FONT_PATH), size)


def centered(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], text: str, face, fill: str) -> None:
    left, top, right, bottom = box
    bounds = draw.textbbox((0, 0), text, font=face)
    width, height = bounds[2] - bounds[0], bounds[3] - bounds[1]
    draw.text((left + (right - left - width) / 2, top + (bottom - top - height) / 2 - bounds[1]), text, font=face, fill=fill)


def box(draw: ImageDraw.ImageDraw, x: int, y: int, width: int, height: int, title: str, lines: list[str], stroke: str = INK) -> None:
    draw.rounded_rectangle((x, y, x + width, y + height), radius=8, fill=WHITE, outline=stroke, width=1)
    centered(draw, (x + 16, y + 19, x + width - 16, y + 47), title, font(18, bold=True), INK)
    if len(lines) == 1:
        centered(draw, (x + 14, y + 63, x + width - 14, y + 90), lines[0], font(14), MUTED)
    else:
        for index, line in enumerate(lines):
            centered(draw, (x + 14, y + 52 + index * 20, x + width - 14, y + 73 + index * 20), line, font(14), MUTED)


def arrow(draw: ImageDraw.ImageDraw, start: tuple[int, int], end: tuple[int, int], color: str = INK, dashed: bool = False) -> None:
    x1, y1 = start
    x2, y2 = end
    if dashed:
        length = ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
        dx, dy = (x2 - x1) / length, (y2 - y1) / length
        step = 8
        distance = 0
        while distance < length - 12:
            segment_end = min(distance + 4, length - 12)
            draw.line((x1 + dx * distance, y1 + dy * distance, x1 + dx * segment_end, y1 + dy * segment_end), fill=color, width=1)
            distance += step
    else:
        draw.line((x1, y1, x2, y2), fill=color, width=1)
    # Filled, compact triangular arrowhead.
    if x1 == x2:
        triangle = [(x2, y2), (x2 - 5, y2 - 9), (x2 + 5, y2 - 9)] if y2 > y1 else [(x2, y2), (x2 - 5, y2 + 9), (x2 + 5, y2 + 9)]
    else:
        triangle = [(x2, y2), (x2 - 9, y2 - 5), (x2 - 9, y2 + 5)] if x2 > x1 else [(x2, y2), (x2 + 9, y2 - 5), (x2 + 9, y2 + 5)]
    draw.polygon(triangle, fill=color)


def curved_return(draw: ImageDraw.ImageDraw) -> None:
    # Cubic Bezier sampled at 1px precision: REST API → Razorpay webhook ingress.
    p0, p1, p2, p3 = (1120, 555), (1120, 885), (80, 890), (80, 500)
    previous = p0
    for step in range(1, 301):
        t = step / 300
        u = 1 - t
        point = (
            u**3 * p0[0] + 3 * u**2 * t * p1[0] + 3 * u * t**2 * p2[0] + t**3 * p3[0],
            u**3 * p0[1] + 3 * u**2 * t * p1[1] + 3 * u * t**2 * p2[1] + t**3 * p3[1],
        )
        draw.line((previous, point), fill=INK, width=1)
        previous = point
    # Return vector is upward when it reaches the left edge of Razorpay Webhooks.
    draw.polygon([(80, 500), (75, 510), (85, 510)], fill=INK)


def main() -> None:
    canvas = Image.new("RGB", (WIDTH, HEIGHT), WHITE)
    draw = ImageDraw.Draw(canvas)

    draw.text((80, 62), "Cadence - Autonomous Payment Recovery", font=font(24, bold=True), fill=INK)
    draw.text((80, 98), "Razorpay-native · audit-anchored · closes in ~4s", font=font(14), fill=MUTED)

    # Primary single-row recovery path (vertically centered at y=500).
    box(draw, 80, 445, 220, 110, "Razorpay Webhooks", ["5 event types"])
    box(draw, 390, 445, 220, 110, "Cadence Engine", ["HMAC verify · classifier", "bandit · Hinglish copy"])
    box(draw, 700, 445, 220, 110, "Channels", ["Email · Voice · PDF · WhatsApp"], BLUE)
    box(draw, 1010, 445, 220, 110, "Razorpay REST API", ["customer.create +", "payment_link.create"], BLUE)
    box(draw, 1280, 390, 240, 110, "Operator SPA", ["Live Recovery · Test Lab · Replay"], MUTED)

    # The audit branch intentionally sits beneath the engine, not in the main customer-facing path.
    box(draw, 390, 675, 220, 110, "Audit Ledger", ["SHA-256 hash-chained,", "append-only"])

    arrow(draw, (300, 500), (390, 500))
    arrow(draw, (610, 500), (700, 500))
    arrow(draw, (920, 500), (1010, 500))
    arrow(draw, (500, 555), (500, 675), dashed=True)
    curved_return(draw)

    # Arrow labels are kept in a dedicated band immediately above or beside their paths.
    centered(draw, (302, 402, 388, 424), "payment_link.paid", font(14), INK)
    centered(draw, (540, 402, 770, 424), "compose + choose channel", font(14), INK)
    centered(draw, (848, 402, 1082, 424), "new payment_link.create", font(14), INK)
    draw.text((530, 615), "append-only · Merkle-anchored", font=font(14), fill=MUTED)
    centered(draw, (510, 842, 760, 865), "closes in ~4s", font(14), BLUE)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(OUT, format="PNG", optimize=True)
    print(f"Wrote {OUT} ({WIDTH}x{HEIGHT})")


if __name__ == "__main__":
    main()
