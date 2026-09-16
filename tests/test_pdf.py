from io import BytesIO
import pytest
from PIL import Image
import pypdf

from core.pdf import PdfRenderError, render_pdf_to_jpeg


def _make_pdf_with_image() -> bytes:
    img = Image.new("RGB", (300, 200), color="blue")
    pdf_buf = BytesIO()
    img.save(pdf_buf, format="PDF")
    return pdf_buf.getvalue()



def _make_pdf_with_text() -> bytes:
    writer = pypdf.PdfWriter()
    page = writer.add_blank_page(width=400, height=600)
    pdf_buf = BytesIO()
    writer.write(pdf_buf)
    return pdf_buf.getvalue()


def test_render_pdf_with_image_returns_jpeg():
    data = _make_pdf_with_image()
    res = render_pdf_to_jpeg(data)
    assert isinstance(res, bytes)
    img = Image.open(BytesIO(res))
    assert img.format == "JPEG"


def test_render_pdf_with_text_returns_jpeg():
    data = _make_pdf_with_text()
    res = render_pdf_to_jpeg(data)
    assert isinstance(res, bytes)
    img = Image.open(BytesIO(res))
    assert img.format == "JPEG"


def test_render_pdf_corrupted_raises_error():
    with pytest.raises(PdfRenderError) as exc_info:
        render_pdf_to_jpeg(b"not-a-valid-pdf-stream")
    assert exc_info.value.code == "PDF_DECODE_FAILED"


def test_render_pdf_empty_raises_error():
    with pytest.raises(PdfRenderError) as exc_info:
        render_pdf_to_jpeg(b"")
    assert exc_info.value.code == "PDF_EMPTY"
