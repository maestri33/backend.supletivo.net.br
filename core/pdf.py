from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageDraw
import pypdf

_MAX_PAGES = 2
_MAX_RENDER_SIDE = 2500.0


class PdfRenderError(ValueError):
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


def render_pdf_to_jpeg(data: bytes) -> bytes:
    """Converte as páginas de um PDF em JPEG único sem dependências C++ (pypdfium2).

    1. Se houver imagens embutidas (ex: RG/CNH escaneados, fotos do gov.br), extrai os bitmaps originais diretamente.
    2. Se for PDF vetorial/digital sem imagem raster, renderiza uma visualização limpa do texto.
    """
    if not data or len(data) == 0:
        raise PdfRenderError("PDF sem páginas.", code="PDF_EMPTY")

    try:
        reader = pypdf.PdfReader(BytesIO(data))
    except Exception as exc:
        raise PdfRenderError(
            "Arquivo não é um PDF válido (corrompido ou protegido).",
            code="PDF_DECODE_FAILED",
        ) from exc

    try:
        num_pages = len(reader.pages)
    except Exception as exc:
        raise PdfRenderError(
            "Arquivo não é um PDF válido (corrompido ou protegido).",
            code="PDF_DECODE_FAILED",
        ) from exc

    if num_pages == 0:
        raise PdfRenderError("PDF sem páginas.", code="PDF_EMPTY")

    pages: list[Image.Image] = []
    max_pages = min(num_pages, _MAX_PAGES)

    for page_index in range(max_pages):
        page = reader.pages[page_index]
        extracted_img = None

        # 1. Tenta extrair imagem embutida de alta resolução da página
        if getattr(page, "images", None):
            try:
                # Pega a maior imagem da página (o documento em si)
                largest_img = max(page.images, key=lambda im: len(im.data))
                extracted_img = Image.open(BytesIO(largest_img.data)).convert("RGB")
            except Exception:
                extracted_img = None

        if extracted_img is not None:
            w, h = extracted_img.size
            if max(w, h) > _MAX_RENDER_SIDE:
                scale = _MAX_RENDER_SIDE / max(w, h)
                extracted_img = extracted_img.resize(
                    (int(w * scale), int(h * scale)), Image.Resampling.LANCZOS
                )
            pages.append(extracted_img)
        else:
            # 2. PDF digital/vetorial sem imagem raster: renderiza texto extraído em folha A4 limpa
            try:
                text = page.extract_text() or ""
            except Exception:
                text = ""
            sheet = Image.new("RGB", (1240, 1754), "white")
            draw = ImageDraw.Draw(sheet)
            y = 50
            for line in text.splitlines()[:80]:
                draw.text((50, y), line[:120], fill="black")
                y += 20
            pages.append(sheet)

    if not pages:
        raise PdfRenderError("PDF sem páginas.", code="PDF_EMPTY")

    if len(pages) == 1:
        sheet = pages[0]
    else:
        width = max(p.width for p in pages)
        total_height = sum(p.height for p in pages)
        sheet = Image.new("RGB", (width, total_height), "white")
        offset_y = 0
        for p in pages:
            offset_x = (width - p.width) // 2
            sheet.paste(p, (offset_x, offset_y))
            offset_y += p.height

    output = BytesIO()
    sheet.save(output, format="JPEG", quality=90)
    return output.getvalue()

