"""Generate brand assets for HACS (icon.png 256x256, logo.png 512x256).

House silhouette + three signal dots = "smart home that stays in sync".
Background is a vertical HA-blue gradient so the asset feels at home next
to the rest of the Home Assistant integration directory.

Re-run after editing:

    .venv/bin/python scripts/generate_brand_assets.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT_DIR = Path(__file__).resolve().parents[1] / "custom_components" / "homekit_smart_sync" / "brand"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Vertical-gradient endpoints — light HA blue at the top, deeper at the bottom.
BG_TOP = (41, 182, 246)
BG_BOTTOM = (2, 136, 209)
FG = (255, 255, 255, 255)
# Picked to read cleanly on top of the mid-gradient hue, doesn't have to
# match either endpoint exactly.
WINDOW = (1, 110, 169, 255)

WORDMARK = (24, 32, 40, 255)
WORDMARK_SUB = (96, 110, 122, 255)


def load_font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates_bold = [
        "/System/Library/Fonts/HelveticaNeue.ttc",
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ]
    candidates_regular = [
        "/System/Library/Fonts/HelveticaNeue.ttc",
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ]
    for path in candidates_bold if bold else candidates_regular:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def gradient_rounded_square(
    size: int,
    top: tuple[int, int, int],
    bottom: tuple[int, int, int],
    radius: int,
) -> Image.Image:
    """Render a top-to-bottom gradient clipped to a rounded square."""
    gradient = Image.new("RGB", (size, size), top)
    gd = ImageDraw.Draw(gradient)
    for y in range(size):
        t = y / max(size - 1, 1)
        gd.line(
            [(0, y), (size, y)],
            fill=(
                round(top[0] + (bottom[0] - top[0]) * t),
                round(top[1] + (bottom[1] - top[1]) * t),
                round(top[2] + (bottom[2] - top[2]) * t),
            ),
        )
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size, size), radius=radius, fill=255)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(gradient, (0, 0), mask)
    return out


def make_icon() -> Image.Image:
    size = 256
    img = gradient_rounded_square(size, BG_TOP, BG_BOTTOM, radius=48)
    draw = ImageDraw.Draw(img)

    # Three signal dots above the roof — read as "broadcasting / in sync".
    # Slight vertical stagger gives a touch of dynamism without being noisy.
    dots = [(-22, 56), (0, 50), (22, 56)]
    for dx, dy in dots:
        cx, cy, r = 128 + dx, dy, 5
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=FG)

    # House body — rounded bottom corners only would be ideal but PIL only
    # offers all-corners rounded rectangles. Slight rounding everywhere
    # keeps the silhouette friendly at small sizes.
    draw.rounded_rectangle((76, 130, 180, 212), radius=10, fill=FG)

    # Roof — overlaps the body top by ~4 px so the seam is invisible.
    draw.polygon([(54, 134), (128, 76), (202, 134)], fill=FG)

    # A single round window adds character and reads as "smart sensor"
    # without needing decorative detail that gets lost at small sizes.
    draw.ellipse((117, 156, 139, 178), fill=WINDOW)

    return img


def make_logo(icon_full: Image.Image) -> Image.Image:
    width, height = 512, 256
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))

    icon_size = 196
    icon = icon_full.resize((icon_size, icon_size), Image.LANCZOS)
    img.paste(icon, (20, (height - icon_size) // 2), icon)

    draw = ImageDraw.Draw(img)
    font_lg = load_font(40, bold=True)
    font_sm = load_font(24)

    text_x = 232
    # Optical centering: HomeKit baseline + Smart Sync below, vertically
    # balanced around the icon's middle.
    draw.text((text_x, 86), "HomeKit", fill=WORDMARK, font=font_lg)
    draw.text((text_x, 138), "Smart Sync", fill=WORDMARK_SUB, font=font_sm)
    return img


def main() -> None:
    icon = make_icon()
    logo = make_logo(icon)
    icon.save(OUT_DIR / "icon.png")
    logo.save(OUT_DIR / "logo.png")
    print(f"wrote {OUT_DIR / 'icon.png'} ({icon.size})")
    print(f"wrote {OUT_DIR / 'logo.png'} ({logo.size})")


if __name__ == "__main__":
    main()
