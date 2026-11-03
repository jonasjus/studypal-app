"""Small real PDFs for tests: pages with a text layer (like a typed exam) or blank ones (like a scan)."""

from __future__ import annotations

import io


def text_pdf(pages: list[str]) -> bytes:
    """A PDF whose pages carry these texts in Helvetica, one line per line of text (Latin-1 only)."""
    objects: list[bytes] = []

    def add(body: bytes) -> int:
        objects.append(body)
        return len(objects)

    catalog = add(b"")  # filled in below, once the page tree's number is known
    font = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    tree = add(b"")
    kids = []
    for text in pages:
        lines = [line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") for line in text.splitlines()]
        stream = "BT /F1 11 Tf 14 TL 50 790 Td " + " ".join(f"({line}) Tj T*" for line in lines) + " ET"
        data = stream.encode("latin-1")
        content = add(b"<< /Length %d >>\nstream\n" % len(data) + data + b"\nendstream")
        kids.append(add(b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 595 842] /Contents %d 0 R "
                        b"/Resources << /Font << /F1 %d 0 R >> >> >>" % (tree, content, font)))
    objects[catalog - 1] = b"<< /Type /Catalog /Pages %d 0 R >>" % tree
    objects[tree - 1] = (b"<< /Type /Pages /Kids [" + b" ".join(b"%d 0 R" % k for k in kids)
                         + b"] /Count %d >>" % len(kids))
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(b"%d 0 obj\n" % i + body + b"\nendobj\n")
    xref = out.tell()
    out.write(b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1))
    for off in offsets:
        out.write(b"%010d 00000 n \n" % off)
    out.write(b"trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, catalog, xref))
    return out.getvalue()


def blank_pdf(n_pages: int, width: float = 595) -> bytes:
    """A PDF of empty pages: no text layer, so every page counts as a scan."""
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument.new()
    for _ in range(n_pages):
        pdf.new_page(width, 842)
    out = io.BytesIO()
    pdf.save(out)
    pdf.close()
    return out.getvalue()
