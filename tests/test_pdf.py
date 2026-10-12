from io import BytesIO
import pytest
from PIL import Image
import pypdf

from core.pdf import PdfRenderError, render_pdf_to_jpeg
from pypdf.generic import DecodedStreamObject, NameObject


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


def test_password_protection_has_actionable_error_code():
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=200, height=100)
    writer.encrypt('test-password')
    buffer = BytesIO()
    writer.write(buffer)
    with pytest.raises(PdfRenderError) as caught:
        render_pdf_to_jpeg(buffer.getvalue())
    assert caught.value.code == 'PDF_PASSWORD_REQUIRED'
    assert 'senha' in str(caught.value)


def test_preserves_vector_content_and_both_pdf_pages():
    writer = pypdf.PdfWriter()
    for color in (b"1 0 0", b"0 0 1"):
        page = writer.add_blank_page(width=200, height=100)
        stream = DecodedStreamObject()
        stream.set_data(color + b" rg 0 0 200 100 re f")
        page[NameObject("/Contents")] = writer._add_object(stream)
    buffer = BytesIO()
    writer.write(buffer)
    image = Image.open(BytesIO(render_pdf_to_jpeg(buffer.getvalue())))
    top = image.getpixel((image.width // 2, image.height // 4))
    bottom = image.getpixel((image.width // 2, image.height * 3 // 4))
    assert top[0] > 240 and top[2] < 15
    assert bottom[2] > 240 and bottom[0] < 15


def test_does_not_silently_truncate_extra_pages():
    writer = pypdf.PdfWriter()
    for _ in range(3):
        writer.add_blank_page(width=200, height=100)
    buffer = BytesIO()
    writer.write(buffer)
    with pytest.raises(PdfRenderError) as error:
        render_pdf_to_jpeg(buffer.getvalue())
    assert error.value.code == "PDF_TOO_MANY_PAGES"
