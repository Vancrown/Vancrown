#!/usr/bin/env python3
"""
Convert a JPG, PNG, WebP, TIFF, or iPhone HEIC/HEIF photo into
assets/portrait.txt for the GitHub profile dashboard.

Recommended with uv:

    uv run --with pillow --with pillow-heif \
      python scripts/photo_to_portrait.py ~/Desktop/photo.HEIC

Common examples:

    # Default: 42 columns × 22 rows, saved to assets/portrait.txt
    uv run --with pillow --with pillow-heif \
      python scripts/photo_to_portrait.py photo.jpg

    # Make the face larger before converting
    uv run --with pillow --with pillow-heif \
      python scripts/photo_to_portrait.py photo.jpg --zoom 1.35

    # Dark photo or reversed-looking output
    uv run --with pillow --with pillow-heif \
      python scripts/photo_to_portrait.py photo.jpg --invert

    # Explicit output path
    uv run --with pillow --with pillow-heif \
      python scripts/photo_to_portrait.py photo.png \
      --output assets/portrait.txt

The script:
1. Reads and auto-rotates the photo using EXIF orientation.
2. Supports transparent PNGs by compositing them on a chosen background.
3. Center-crops the photo to the dashboard portrait aspect ratio.
4. Applies grayscale, contrast, sharpening, and optional edge enhancement.
5. Maps brightness levels to ASCII characters.
6. Writes the result to assets/portrait.txt.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

try:
    from PIL import (
        Image,
        ImageChops,
        ImageEnhance,
        ImageFilter,
        ImageOps,
        UnidentifiedImageError,
    )
except ImportError as exc:
    raise SystemExit(
        "Pillow is required.\n\n"
        "Run with uv:\n"
        "  uv run --with pillow --with pillow-heif "
        "python scripts/photo_to_portrait.py PHOTO\n\n"
        "Or install it:\n"
        "  python -m pip install Pillow pillow-heif"
    ) from exc


SUPPORTED_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".tif",
    ".tiff",
    ".bmp",
    ".heic",
    ".heif",
}

# Ordered from lightest to darkest.
DEFAULT_CHARSET = " .,:;irsXA253hMHGS#9B&@"


def register_heif_if_available() -> bool:
    """Register HEIC/HEIF support when pillow-heif is installed."""
    try:
        from pillow_heif import register_heif_opener
    except ImportError:
        return False

    register_heif_opener()
    return True


def default_output_path() -> Path:
    """
    Use <project>/assets/portrait.txt when this file is inside scripts/.
    Otherwise use ./assets/portrait.txt from the current working directory.
    """
    script_path = Path(__file__).resolve()
    if script_path.parent.name == "scripts":
        return script_path.parent.parent / "assets" / "portrait.txt"
    return Path.cwd() / "assets" / "portrait.txt"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert a photo into a GitHub dashboard ASCII portrait.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("photo", type=Path, help="Input JPG, PNG, HEIC, or other supported image")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Output text file; defaults to assets/portrait.txt",
    )
    parser.add_argument(
        "--width",
        type=int,
        default=42,
        help="Number of ASCII columns",
    )
    parser.add_argument(
        "--height",
        type=int,
        default=22,
        help="Number of ASCII rows; the dashboard displays at most 24",
    )
    parser.add_argument(
        "--zoom",
        type=float,
        default=1.0,
        help="Zoom into the center before conversion; values above 1 make the face larger",
    )
    parser.add_argument(
        "--shift-x",
        type=float,
        default=0.0,
        help="Horizontal crop shift from -1.0 (left) to 1.0 (right)",
    )
    parser.add_argument(
        "--shift-y",
        type=float,
        default=0.0,
        help="Vertical crop shift from -1.0 (up) to 1.0 (down)",
    )
    parser.add_argument(
        "--contrast",
        type=float,
        default=1.35,
        help="Contrast multiplier",
    )
    parser.add_argument(
        "--brightness",
        type=float,
        default=1.0,
        help="Brightness multiplier",
    )
    parser.add_argument(
        "--sharpness",
        type=float,
        default=1.25,
        help="Sharpness multiplier",
    )
    parser.add_argument(
        "--edge-strength",
        type=float,
        default=0.18,
        help="Darken detected edges to preserve facial details; use 0 to disable",
    )
    parser.add_argument(
        "--autocontrast-cutoff",
        type=float,
        default=1.0,
        help="Percent of darkest/lightest pixels clipped by autocontrast",
    )
    parser.add_argument(
        "--white-cutoff",
        type=int,
        default=248,
        help="Pixels at or above this brightness become spaces; use 255 to disable",
    )
    parser.add_argument(
        "--black-cutoff",
        type=int,
        default=0,
        help="Pixels at or below this brightness use the darkest character",
    )
    parser.add_argument(
        "--invert",
        action="store_true",
        help="Reverse image brightness before mapping to characters",
    )
    parser.add_argument(
        "--background",
        choices=("white", "black"),
        default="white",
        help="Background used behind transparent PNG pixels",
    )
    parser.add_argument(
        "--charset",
        default=DEFAULT_CHARSET,
        help="Characters ordered from lightest to darkest",
    )
    parser.add_argument(
        "--no-crop",
        action="store_true",
        help="Resize the whole photo instead of center-cropping it",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Do not print the generated ASCII preview",
    )
    return parser.parse_args(argv)


def validate_args(args: argparse.Namespace) -> None:
    if not args.photo.exists():
        raise SystemExit(f"Input photo does not exist: {args.photo}")
    if not args.photo.is_file():
        raise SystemExit(f"Input path is not a file: {args.photo}")

    ext = args.photo.suffix.lower()
    if ext and ext not in SUPPORTED_EXTENSIONS:
        print(
            f"Warning: extension {ext!r} is unusual. Pillow will still try to open it.",
            file=sys.stderr,
        )

    if args.width < 8:
        raise SystemExit("--width must be at least 8")
    if not 4 <= args.height <= 24:
        raise SystemExit("--height must be between 4 and 24 for this dashboard")
    if args.zoom < 1.0:
        raise SystemExit("--zoom must be at least 1.0")
    if not -1.0 <= args.shift_x <= 1.0:
        raise SystemExit("--shift-x must be between -1.0 and 1.0")
    if not -1.0 <= args.shift_y <= 1.0:
        raise SystemExit("--shift-y must be between -1.0 and 1.0")
    if args.contrast <= 0 or args.brightness <= 0 or args.sharpness <= 0:
        raise SystemExit("Contrast, brightness, and sharpness must be greater than 0")
    if not 0.0 <= args.edge_strength <= 1.0:
        raise SystemExit("--edge-strength must be between 0 and 1")
    if not 0.0 <= args.autocontrast_cutoff < 50.0:
        raise SystemExit("--autocontrast-cutoff must be in [0, 50)")
    if not 0 <= args.black_cutoff <= 255:
        raise SystemExit("--black-cutoff must be between 0 and 255")
    if not 0 <= args.white_cutoff <= 255:
        raise SystemExit("--white-cutoff must be between 0 and 255")
    if args.black_cutoff > args.white_cutoff:
        raise SystemExit("--black-cutoff cannot exceed --white-cutoff")
    if len(args.charset) < 2:
        raise SystemExit("--charset must contain at least two characters")
    if "\n" in args.charset or "\r" in args.charset:
        raise SystemExit("--charset cannot contain line breaks")


def open_image(path: Path, background: str) -> Image.Image:
    heif_registered = register_heif_if_available()

    if path.suffix.lower() in {".heic", ".heif"} and not heif_registered:
        raise SystemExit(
            "This is an HEIC/HEIF image, but pillow-heif is not installed.\n\n"
            "Recommended:\n"
            "  uv run --with pillow --with pillow-heif "
            "python scripts/photo_to_portrait.py PHOTO.HEIC\n\n"
            "Or install it:\n"
            "  python -m pip install pillow-heif"
        )

    try:
        image = Image.open(path)
        image.load()
    except UnidentifiedImageError as exc:
        raise SystemExit(
            f"Could not decode the image: {path}\n"
            "For iPhone HEIC files, install pillow-heif."
        ) from exc
    except OSError as exc:
        raise SystemExit(f"Could not open image {path}: {exc}") from exc

    image = ImageOps.exif_transpose(image)

    # Preserve transparent subjects by compositing them onto a predictable background.
    if image.mode in {"RGBA", "LA"} or (
        image.mode == "P" and "transparency" in image.info
    ):
        rgba = image.convert("RGBA")
        bg_value = 255 if background == "white" else 0
        canvas = Image.new("RGBA", rgba.size, (bg_value, bg_value, bg_value, 255))
        image = Image.alpha_composite(canvas, rgba).convert("RGB")
    else:
        image = image.convert("RGB")

    return image


def crop_for_ascii(
    image: Image.Image,
    columns: int,
    rows: int,
    zoom: float,
    shift_x: float,
    shift_y: float,
) -> Image.Image:
    """
    Crop to the visual aspect ratio produced by the dashboard's monospace font.

    In update_profile.py, characters are roughly 7.8 px wide and lines are 18 px
    tall, so one text cell has a width/height ratio near 0.433.
    """
    cell_aspect = 0.433
    target_aspect = (columns * cell_aspect) / rows

    width, height = image.size
    source_aspect = width / height

    if source_aspect > target_aspect:
        crop_height = height
        crop_width = int(round(height * target_aspect))
    else:
        crop_width = width
        crop_height = int(round(width / target_aspect))

    crop_width = max(1, int(round(crop_width / zoom)))
    crop_height = max(1, int(round(crop_height / zoom)))

    free_x = max(0, width - crop_width)
    free_y = max(0, height - crop_height)

    # shift -1 => start edge, 0 => center, +1 => end edge
    left = int(round(free_x * ((shift_x + 1.0) / 2.0)))
    top = int(round(free_y * ((shift_y + 1.0) / 2.0)))
    left = min(max(0, left), width - crop_width)
    top = min(max(0, top), height - crop_height)

    return image.crop((left, top, left + crop_width, top + crop_height))


def preprocess(image: Image.Image, args: argparse.Namespace) -> Image.Image:
    if not args.no_crop:
        image = crop_for_ascii(
            image,
            columns=args.width,
            rows=args.height,
            zoom=args.zoom,
            shift_x=args.shift_x,
            shift_y=args.shift_y,
        )

    image = image.resize((args.width, args.height), Image.Resampling.LANCZOS)
    gray = ImageOps.grayscale(image)

    if args.autocontrast_cutoff > 0:
        gray = ImageOps.autocontrast(gray, cutoff=args.autocontrast_cutoff)

    if args.brightness != 1.0:
        gray = ImageEnhance.Brightness(gray).enhance(args.brightness)
    if args.contrast != 1.0:
        gray = ImageEnhance.Contrast(gray).enhance(args.contrast)
    if args.sharpness != 1.0:
        gray = ImageEnhance.Sharpness(gray).enhance(args.sharpness)

    if args.edge_strength > 0:
        # FIND_EDGES returns bright contours. Subtracting a fraction of them
        # darkens contours and preserves eyes, nose, jawline, hair, and clothing.
        edges = gray.filter(ImageFilter.FIND_EDGES)
        edges = ImageOps.autocontrast(edges)
        edges = edges.point(lambda value: int(value * args.edge_strength))
        gray = ImageChops.subtract(gray, edges)

    if args.invert:
        gray = ImageOps.invert(gray)

    return gray


def image_to_ascii(image: Image.Image, args: argparse.Namespace) -> str:
    charset = args.charset
    darkest_index = len(charset) - 1
    get_pixels = getattr(image, "get_flattened_data", image.getdata)
    pixels = list(get_pixels())
    lines: list[str] = []

    for row_index in range(args.height):
        start = row_index * args.width
        row = pixels[start : start + args.width]
        characters: list[str] = []

        for brightness in row:
            if brightness >= args.white_cutoff:
                char = charset[0]
            elif brightness <= args.black_cutoff:
                char = charset[darkest_index]
            else:
                # charset is light-to-dark, while brightness is dark-to-light.
                darkness = 1.0 - (brightness / 255.0)
                index = int(round(darkness * darkest_index))
                index = min(max(index, 0), darkest_index)
                char = charset[index]
            characters.append(char)

        # Right-trim only. Leading spaces preserve the portrait alignment.
        lines.append("".join(characters).rstrip())

    # Keep the requested row count but remove completely empty rows at the
    # bottom. This avoids unnecessary blank lines in the SVG.
    while lines and not lines[-1]:
        lines.pop()

    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    validate_args(args)

    output = args.output or default_output_path()
    image = open_image(args.photo, args.background)
    prepared = preprocess(image, args)
    portrait = image_to_ascii(prepared, args)

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(portrait, encoding="utf-8")

    if not args.quiet:
        print()
        print(portrait, end="")
        print(f"\nSaved portrait to: {output.resolve()}")
        print(
            "\nNext, regenerate the dashboard:\n"
            "  python scripts/update_profile.py --mock\n"
            "or push the portrait and let GitHub Actions refresh the live metrics."
        )
    else:
        print(output.resolve())

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
