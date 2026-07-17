from io import BytesIO

import pytest
from PIL import Image, ImageDraw, ImageFilter

from app.services.ocr_service import OCRError, run_ocr


def _text_image(text: str, size: tuple[int, int] = (500, 120)) -> Image.Image:
    image = Image.new("RGB", size, color="white")
    ImageDraw.Draw(image).text((10, 40), text, fill="black")
    return image


def _png_bytes_with_text(text: str) -> bytes:
    buffer = BytesIO()
    _text_image(text).save(buffer, format="PNG")
    return buffer.getvalue()


def test_run_ocr_extracts_text_from_image():
    content = _png_bytes_with_text("FACTURA Total: 45000")

    result = run_ocr(content, "image/png")

    assert "FACTURA" in result.raw_text
    assert "45000" in result.raw_text
    assert result.page_count == 1
    assert result.confidence_score is not None
    assert 0 <= result.confidence_score <= 100


def test_run_ocr_handles_multi_page_pdf():
    page1 = _text_image("PAGINA UNO FACTURA 111")
    page2 = _text_image("PAGINA DOS TOTAL 222")
    buffer = BytesIO()
    page1.save(buffer, format="PDF", save_all=True, append_images=[page2])

    result = run_ocr(buffer.getvalue(), "application/pdf")

    assert result.page_count == 2
    assert "111" in result.raw_text
    assert "222" in result.raw_text


def test_run_ocr_flags_skewed_image_with_lower_confidence():
    # A phone photo of a receipt is rarely perfectly level. Tesseract has no
    # built-in deskew step, so even a mild tilt measurably hurts accuracy
    # (e.g. "987" misread as "ga7"). Rather than expecting perfect text
    # recovery, this asserts the pipeline surfaces that degradation as a
    # lower confidence_score -- the signal Step 4 (AI fallback) will use to
    # decide when OCR results need a second pass.
    text = "RECIBO 987 TOTAL 30000"
    straight_buffer = BytesIO()
    _text_image(text).save(straight_buffer, format="PNG")
    skewed_buffer = BytesIO()
    _text_image(text).rotate(6, expand=True, fillcolor="white").save(skewed_buffer, format="PNG")

    straight_result = run_ocr(straight_buffer.getvalue(), "image/png")
    skewed_result = run_ocr(skewed_buffer.getvalue(), "image/png")

    assert straight_result.confidence_score is not None
    assert skewed_result.confidence_score is not None
    assert skewed_result.confidence_score < straight_result.confidence_score


def test_run_ocr_on_blurry_low_confidence_image_does_not_crash():
    image = _text_image("FACTURA BORROSA 555").filter(ImageFilter.GaussianBlur(radius=3))
    buffer = BytesIO()
    image.save(buffer, format="PNG")

    result = run_ocr(buffer.getvalue(), "image/png")

    assert isinstance(result.raw_text, str)
    assert result.page_count == 1


def test_run_ocr_on_blank_image_returns_empty_text_and_no_confidence():
    blank = Image.new("RGB", (300, 100), color="white")
    buffer = BytesIO()
    blank.save(buffer, format="PNG")

    result = run_ocr(buffer.getvalue(), "image/png")

    assert result.raw_text == ""
    assert result.confidence_score is None
    assert result.page_count == 1


def test_run_ocr_raises_ocr_error_for_corrupted_image_bytes():
    with pytest.raises(OCRError):
        run_ocr(b"this is not a real image file", "image/png")


def test_run_ocr_raises_ocr_error_for_corrupted_pdf_bytes():
    with pytest.raises(OCRError):
        run_ocr(b"%PDF-1.4 not actually a valid pdf structure", "application/pdf")
