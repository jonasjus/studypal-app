"""Turning exam files into pages: the text of each PDF page where it has one, and an image of the page
where it doesn't (a scan).

A PDF's text layer comes out through pypdfium2. A page with little or no text is drawn as an image
instead, for the model to transcribe (core/ingest.py). Formulas in a text layer come out as loose
characters; the model that finds the questions writes them back as LaTeX. Photos are turned into JPEGs and shrunk to a size that reads well without
wasting the request (Pillow). HEIC photos from iPhones are converted with the Mac's own `sips`, since
Pillow can't open them; elsewhere they need to be saved as JPG first. Text files are passed on as text.
"""

from __future__ import annotations

import io
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

LONG_SIDE = 1700  # pixels: small print stays legible, a page stays a few hundred KB
MAX_PAGES = 40  # per file


MIN_TEXT = 120  # characters: a page with less text than this is taken to be a scan


class PageError(Exception):
    """A file that can't be turned into pages; the message says why."""


@dataclass
class Page:
    """One page of a file: its text, or (when the text isn't enough) an image for the model to read."""

    number: int
    text: str = ""
    image: bytes | None = None  # JPEG; set when the page needs reading by the model


def needs_reading(text: str) -> bool:
    """Whether the text layer is too thin to use: a scan (or a page that's only a picture)."""
    return len("".join(text.split())) < MIN_TEXT


def clean_text(text: str) -> str:
    """A text layer tidied into plain Markdown-safe lines: no hyphenation at line ends, no runs of blanks."""
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


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


def pdf_text_pages(name: str, data: bytes) -> list[Page]:
    """Each page's text, and an image of the pages whose text isn't enough."""
    import pypdfium2 as pdfium

    try:
        pdf = pdfium.PdfDocument(data)
    except Exception:
        raise PageError(f"“{name}” can't be opened as a PDF. Is it damaged, or protected with a password?") from None
    try:
        if len(pdf) > MAX_PAGES:
            raise PageError(f"“{name}” has {len(pdf)} pages; StudyPal reads at most {MAX_PAGES}. Split it into parts.")
        out = []
        for i, page in enumerate(pdf, start=1):
            text = clean_text(page.get_textpage().get_text_bounded())
            image = None
            if needs_reading(text):
                width, height = page.get_size()
                image = _jpeg(page.render(scale=LONG_SIDE / max(width, height)).to_pil())
            out.append(Page(i, text, image))
        return out
    finally:
        pdf.close()


def to_pages(name: str, mime: str, data: bytes) -> list[Page]:
    """A file as pages: a PDF page by page, a photo as one page to read, a text file as one page of text."""
    if mime == "application/pdf":
        return pdf_text_pages(name, data)
    if mime.startswith("image/"):
        return [Page(1, "", image_page(name, mime, data))]
    return [Page(1, data.decode("utf-8", errors="replace")[:200_000])]
