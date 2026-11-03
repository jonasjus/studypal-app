"""Turning exam files into what Groq can read: page images (JPEG) and plain text.

Groq can't read PDFs, so each PDF page is drawn as an image (pypdfium2). Photos are turned into JPEGs
and shrunk to a size that reads well without wasting the request (Pillow). HEIC photos from iPhones are
converted with the Mac's own `sips`, since Pillow can't open them; elsewhere they need to be saved as
JPG first. Text files are passed on as text.
"""

from __future__ import annotations

import io
import subprocess
import sys
import tempfile
from pathlib import Path

LONG_SIDE = 1700  # pixels: small print stays legible, a page stays a few hundred KB
MAX_PAGES = 40  # per file


class PageError(Exception):
    """A file that can't be turned into pages; the message says why."""


def _jpeg(image) -> bytes:  # a PIL image
    image = image.convert("RGB")
    scale = LONG_SIDE / max(image.size)
    if scale < 1:
        image = image.resize((round(image.width * scale), round(image.height * scale)))
    out = io.BytesIO()
    image.save(out, "JPEG", quality=85, optimize=True)
    return out.getvalue()


def pdf_pages(name: str, data: bytes) -> list[bytes]:
    import pypdfium2 as pdfium

    try:
        pdf = pdfium.PdfDocument(data)
    except Exception:
        raise PageError(f"“{name}” can't be opened as a PDF. Is it damaged, or protected with a password?") from None
    try:
        if len(pdf) > MAX_PAGES:
            raise PageError(f"“{name}” has {len(pdf)} pages; StudyPal reads at most {MAX_PAGES}. Split it into parts.")
        pages = []
        for page in pdf:
            width, height = page.get_size()  # in points (1/72 inch)
            bitmap = page.render(scale=LONG_SIDE / max(width, height))
            pages.append(_jpeg(bitmap.to_pil()))
        return pages
    finally:
        pdf.close()


def _heic(name: str, data: bytes) -> bytes:
    if sys.platform != "darwin":
        raise PageError(f"“{name}” is an iPhone photo (HEIC), which can't be read here. Save it as JPG and add that instead.")
    with tempfile.TemporaryDirectory() as folder:
        src, dst = Path(folder) / "in.heic", Path(folder) / "out.jpg"
        src.write_bytes(data)
        done = subprocess.run(["sips", "-s", "format", "jpeg", str(src), "--out", str(dst)], capture_output=True, timeout=60)
        if done.returncode != 0 or not dst.exists():
            raise PageError(f"“{name}” couldn't be converted. Save it as JPG and add that instead.")
        return dst.read_bytes()


def image_page(name: str, mime: str, data: bytes) -> bytes:
    from PIL import Image, ImageOps

    if mime in ("image/heic", "image/heif"):
        data = _heic(name, data)
    try:
        image = Image.open(io.BytesIO(data))
        image = ImageOps.exif_transpose(image)  # phone photos come sideways otherwise
    except Exception:
        raise PageError(f"“{name}” can't be opened as a picture.") from None
    return _jpeg(image)


def split(name: str, mime: str, data: bytes) -> tuple[list[bytes], str]:
    """(page images, text) for one file: a PDF or photo gives images, a text file gives text."""
    if mime == "application/pdf":
        return pdf_pages(name, data), ""
    if mime.startswith("image/"):
        return [image_page(name, mime, data)], ""
    return [], data.decode("utf-8", errors="replace")
