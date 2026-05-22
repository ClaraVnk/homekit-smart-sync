"""Generate placeholder brand assets for HACS (icon.png 256x256, logo.png 512x256).

Minimalist HA-blue rounded square + 'HK' monogram. Designed to be inoffensive
while a proper visual identity is being designed. Re-run any time:

    .venv/bin/python scripts/generate_brand_assets.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT_DIR = Path(__file__).resolve().parents[1] / "custom_components" / "homekit_smart_sync" / "brand"
OUT_DIR.mkdir(parents=True, exist_ok=True)

BG = (3, 169, 244, 255)  # Home Assistant blue
FG = (255, 255, 255, 255)
WORDMARK = (36, 41, 47, 255)
WORDMARK_SUB = (110, 119, 129, 255)


def load_font(size: int) -> ImageFont.FreeTypeFont:
    """Try a few common macOS / Linux font paths, fall back to PIL default."""
    candidates = [
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/HelveticaNeue.ttc",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def make_icon() -> Image.Image:
    size = 256
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((0, 0, size, size), radius=48, fill=BG)

    font = load_font(120)
    text = "HK"
    bbox = draw.textbbox((0, 0), text, font=font)
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]
    # Optical centering: shift up slightly to account for font baseline.
    x = (size - w) / 2 - bbox[0]
    y = (size - h) / 2 - bbox[1] - 6
    draw.text((x, y), text, fill=FG, font=font)
    return img


def make_logo(icon_full: Image.Image) -> Image.Image:
    width, height = 512, 256
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))

    # Icon on the left, centered vertically.
    icon_size = 180
    icon = icon_full.resize((icon_size, icon_size), Image.LANCZOS)
    img.paste(icon, (28, (height - icon_size) // 2), icon)

    draw = ImageDraw.Draw(img)
    font_lg = load_font(34)
    font_sm = load_font(22)

    text_x = 232
    draw.text((text_x, 92), "HomeKit", fill=WORDMARK, font=font_lg)
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
