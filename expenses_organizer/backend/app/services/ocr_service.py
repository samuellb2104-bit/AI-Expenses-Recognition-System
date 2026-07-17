from __future__ import annotations

import os
from dataclasses import dataclass
from io import BytesIO

import pytesseract
from PIL import Image, UnidentifiedImageError
from pdf2image import convert_from_bytes
from pdf2image.exceptions import PDFPageCountError, PDFSyntaxError
from pytesseract import Output

from app.core.config import settings

PDF_MIME_TYPE = "application/pdf"


class OCRError(RuntimeError):
    pass


@dataclass
class OCRResult:
    raw_text: str
    confidence_score: float | None
    page_count: int


def _configure_tesseract() -> None:
    if settings.tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = settings.tesseract_cmd
    if settings.tessdata_prefix:
        os.environ["TESSDATA_PREFIX"] = settings.tessdata_prefix


def _images_from_content(content: bytes, mime_type: str | None) -> list[Image.Image]:
    if mime_type == PDF_MIME_TYPE:
        try:
            return convert_from_bytes(content, poppler_path=settings.poppler_path)
        except (PDFPageCountError, PDFSyntaxError) as exc:
            raise OCRError(f"Could not read PDF for OCR: {exc}") from exc

    try:
        return [Image.open(BytesIO(content))]
    except UnidentifiedImageError as exc:
        raise OCRError(f"Could not read image for OCR: {exc}") from exc


def _extract_page_text(image: Image.Image) -> tuple[str, list[float]]:
    data = pytesseract.image_to_data(image, lang=settings.ocr_languages, output_type=Output.DICT)
    words = []
    confidences = []
    for text, confidence in zip(data["text"], data["conf"]):
        stripped = text.strip()
        if not stripped:
            continue
        words.append(stripped)
        try:
            conf_value = float(confidence)
        except (TypeError, ValueError):
            continue
        if conf_value >= 0:
            confidences.append(conf_value)
    return " ".join(words), confidences


def run_ocr(content: bytes, mime_type: str | None) -> OCRResult:
    _configure_tesseract()
    images = _images_from_content(content, mime_type)

    page_texts = []
    all_confidences: list[float] = []
    try:
        for image in images:
            text, confidences = _extract_page_text(image)
            page_texts.append(text)
            all_confidences.extend(confidences)
    except pytesseract.TesseractNotFoundError as exc:
        raise OCRError(
            "Tesseract executable not found. Set TESSERACT_CMD or install Tesseract OCR."
        ) from exc
    except pytesseract.TesseractError as exc:
        raise OCRError(f"Tesseract failed to process the document: {exc}") from exc

    raw_text = "\n\n".join(page_texts).strip()
    confidence_score = round(sum(all_confidences) / len(all_confidences), 2) if all_confidences else None

    return OCRResult(raw_text=raw_text, confidence_score=confidence_score, page_count=len(images))
