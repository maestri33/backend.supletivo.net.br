from __future__ import annotations

from io import BytesIO

import pypdfium2 as pdfium
from PIL import Image

_MAX_PAGES = 2
_MAX_RENDER_SIDE = 2500.0


class PdfRenderError(ValueError):
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


def render_pdf_to_jpeg(data: bytes) -> bytes:
    try:
        pdf = pdfium.PdfDocument(data)
        pages = []
        for page_index in range(min(len(pdf), _MAX_PAGES)):
            page = pdf[page_index]
            width, height = page.get_size()
            scale = min(2.0, _MAX_RENDER_SIDE / max(width, height, 1.0))
            pages.append(page.render(scale=scale).to_pil())
    except Exception as exc:
        raise PdfRenderError(
            "Arquivo não é um PDF válido (corrompido ou protegido).",
            code="PDF_DECODE_FAILED",
        ) from exc

    if not pages:
        raise PdfRenderError("PDF sem páginas.", code="PDF_EMPTY")

    if len(pages) == 1:
        sheet = pages[0].convert("RGB")
    else:
        width = max(page.width for page in pages)
        sheet = Image.new("RGB", (width, sum(page.height for page in pages)), "white")
        offset_y = 0
        for page in pages:
            sheet.paste(page.convert("RGB"), (0, offset_y))
            offset_y += page.height

    output = BytesIO()
    sheet.save(output, format="JPEG", quality=90)
    return output.getvalue()
