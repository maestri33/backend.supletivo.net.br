from __future__ import annotations

from io import BytesIO
import subprocess
import sys

from PIL import Image

_MAX_PAGES = 2
_MAX_RENDER_SIDE = 2500
_MAX_FILE_BYTES = 15 * 1024 * 1024


class PdfRenderError(ValueError):
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


def render_pdf_to_jpeg(data: bytes) -> bytes:
    """Render both pages, preserving text, photographs and their actual positions.

    PDFium runs in a child process: simultaneous web threads cannot corrupt it, and a
    malformed document or native renderer crash cannot kill the web/queue worker.
    """
    if not data:
        raise PdfRenderError("PDF sem páginas.", code="PDF_EMPTY")
    if len(data) > _MAX_FILE_BYTES:
        raise PdfRenderError("PDF deve ter até 15 MB.", code="PDF_TOO_LARGE")
    try:
        result = subprocess.run([sys.executable, "-m", "core.pdf"], input=data,
                                capture_output=True, timeout=20, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PdfRenderError("Não foi possível renderizar o PDF.", code="PDF_RENDER_FAILED") from exc
    if result.returncode or not result.stdout.startswith(b"\xff\xd8"):
        code = result.stderr.decode("ascii", errors="ignore").strip()
        if code == "PDF_TOO_MANY_PAGES":
            raise PdfRenderError("Envie um PDF com até duas páginas do documento.", code=code)
        if code == "PDF_EMPTY":
            raise PdfRenderError("PDF sem páginas.", code=code)
        if code == "PDF_PASSWORD_REQUIRED":
            raise PdfRenderError("Este PDF está protegido por senha. Remova a senha ou envie uma foto do documento.", code=code)
        raise PdfRenderError("PDF inválido, protegido ou não renderizável.", code="PDF_DECODE_FAILED")
    return result.stdout


def _render_pages(data: bytes) -> bytes:
    import pypdfium2 as pdfium

    pages: list[Image.Image] = []
    with pdfium.PdfDocument(data) as document:
        if not len(document):
            raise PdfRenderError("PDF sem páginas.", code="PDF_EMPTY")
        if len(document) > _MAX_PAGES:
            raise PdfRenderError("PDF com mais de duas páginas.", code="PDF_TOO_MANY_PAGES")
        for index in range(len(document)):
            page = document[index]
            try:
                width, height = page.get_size()
                if width <= 0 or height <= 0:
                    raise ValueError("Invalid page dimensions")
                bitmap = page.render(scale=min(3, _MAX_RENDER_SIDE / max(width, height)))
                try:
                    pages.append(bitmap.to_pil().convert("RGB"))
                finally:
                    bitmap.close()
            finally:
                page.close()
    sheet = Image.new("RGB", (max(p.width for p in pages), sum(p.height for p in pages)), "white")
    offset = 0
    for page in pages:
        sheet.paste(page, ((sheet.width - page.width) // 2, offset))
        offset += page.height
    output = BytesIO()
    sheet.save(output, format="JPEG", quality=90)
    return output.getvalue()


if __name__ == "__main__":
    try:
        sys.stdout.buffer.write(_render_pages(sys.stdin.buffer.read(_MAX_FILE_BYTES + 1)))
    except PdfRenderError as exc:
        sys.stderr.write(exc.code)
        sys.exit(1)
    except Exception as exc:
        import pypdfium2.raw as pdfium_c
        code = "PDF_PASSWORD_REQUIRED" if getattr(exc, "err_code", None) == pdfium_c.FPDF_ERR_PASSWORD else "PDF_DECODE_FAILED"
        sys.stderr.write(code)
        sys.exit(1)

