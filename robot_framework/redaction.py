"""True PDF redaction for KontAKT.

``redact_pdf`` blacks out the given rectangles **and removes the underlying
text / image content** (not just an overlay) using PyMuPDF's redaction
annotations. Coordinates are fractions of the page (0..1, top-left origin) —
the same shape the OCR screening and the in-browser editor produce.
"""
from __future__ import annotations


def redact_pdf(src_path: str, out_path: str, rects: list[dict], *, log=None) -> int:
    """Apply true redactions to *src_path*, writing the result to *out_path*.

    ``rects``: list of ``{"page": <1-based>, "x0","y0","x1","y1"}`` as page
    fractions (0..1, top-left origin). Returns the number of boxes applied.
    """
    log = log or (lambda *_: None)
    import fitz  # PyMuPDF — lazy import

    by_page: dict[int, list] = {}
    for r in rects or []:
        try:
            page = int(r["page"])
        except (KeyError, TypeError, ValueError):
            continue
        by_page.setdefault(page, []).append(r)

    applied = 0
    with fitz.open(src_path) as doc:
        for pno, page_rects in by_page.items():
            if pno < 1 or pno > doc.page_count:
                continue
            page = doc[pno - 1]
            pw, ph = page.rect.width, page.rect.height
            added_here = False
            for r in page_rects:
                try:
                    rect = fitz.Rect(
                        float(r["x0"]) * pw, float(r["y0"]) * ph,
                        float(r["x1"]) * pw, float(r["y1"]) * ph,
                    )
                except (KeyError, TypeError, ValueError):
                    continue
                rect.normalize()
                if rect.is_empty or rect.is_infinite:
                    continue
                page.add_redact_annot(rect, fill=(0, 0, 0))
                added_here = True
                applied += 1
            if added_here:
                page.apply_redactions()  # deletes the content under each box, then paints it
        doc.save(out_path, garbage=4, deflate=True)
    log(f"Redacted {applied} box(es) across {len(by_page)} page(s).")
    return applied
