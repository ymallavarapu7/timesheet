"""
Document extraction pipeline.
Extracts raw text (or structured Vision JSON) from PDF, spreadsheet, and image attachments.

Extraction order (port of extraction_service.ts):
  Spreadsheet  → native XLSX/CSV parser → text
  PDF          → native text (pdfplumber) → if > 100 chars done
                 else pdftoppm → Vision API (all pages) → JSON
                 else Tesseract OCR → text
  Image        → Vision API → JSON
                 else Tesseract OCR → text
"""

import csv
import io
import json
import logging
import re
from pathlib import Path
from typing import Literal

from app.core.config import settings

logger = logging.getLogger(__name__)


def _detect_tesseract_lang(text_sample: str) -> str:
    """Detect language from a text sample for Tesseract. Falls back to 'eng'."""
    try:
        from langdetect import detect
        lang_code = detect(text_sample)
        # Map common langdetect codes to Tesseract language codes
        LANG_MAP = {
            "en": "eng", "fr": "fra", "de": "deu", "es": "spa", "it": "ita",
            "pt": "por", "nl": "nld", "pl": "pol", "ru": "rus", "ja": "jpn",
            "zh-cn": "chi_sim", "zh-tw": "chi_tra", "ko": "kor", "ar": "ara",
            "hi": "hin", "tr": "tur", "vi": "vie", "th": "tha",
        }
        return LANG_MAP.get(lang_code, "eng")
    except Exception:
        return "eng"

ExtractionMethodType = Literal[
    "native_spreadsheet",
    "native_pdf",
    "tesseract",
    "vision_api",
    "failed",
]

OCR_CONFIDENCE_THRESHOLD = 70.0

SPREADSHEET_MIME_TYPES = {
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "text/csv",
    "application/csv",
}

IMAGE_MIME_TYPES = {
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/tiff",
    "image/bmp",
}

# Vision prompt — copied exactly from extraction_service.ts
VISION_PROMPT = (
    "Extract all timesheet data from this image. "
    "The image may contain one timesheet or multiple weekly/monthly timesheets. "
    "For calendar-style weekly or monthly timesheets, treat the columns as "
    "Monday through Sunday when the header shows Mo/Tu/We/Th/Fr/Sa/Su. "
    "If the sheet shows only five working days with hours, map them to Monday "
    "through Friday unless weekend hours are explicitly entered. "
    "Do not create weekend line items when Saturday/Sunday cells show 0 or blank, "
    "and do not move Friday hours onto Saturday or Sunday. "
    "If the image is a summary or pivot sheet showing categories and totals "
    "rather than daily dated entries, do not invent a repeated work_date for "
    "each category row; instead infer the month/period from tokens like 2/26 "
    "and return an empty line_items array. "
    "Return only valid JSON with a top-level field timesheets, where timesheets "
    "is an array of objects with fields: employee_name, client_name, "
    "period_start (YYYY-MM-DD), period_end (YYYY-MM-DD), total_hours (number), "
    "line_items (array of {work_date, hours, description, project_code}), "
    "extraction_confidence (0-1), uncertain_fields (array of field names)."
)


def _validate_vision_timesheet(ts: dict) -> bool:
    """Basic structural validation of a vision-extracted timesheet."""
    if not isinstance(ts, dict):
        return False
    line_items = ts.get("line_items")
    if line_items is not None:
        if not isinstance(line_items, list):
            return False
        for item in line_items:
            if not isinstance(item, dict):
                return False
    return True


class ExtractionResult:
    def __init__(
        self,
        text: str,
        method: ExtractionMethodType,
        confidence: float | None = None,
        error: str | None = None,
        vision_timesheets: list[dict] | None = None,
    ) -> None:
        self.text = text
        self.method = method
        self.confidence = confidence
        self.error = error
        # Populated when Vision API returns structured JSON directly.
        # When set, the pipeline skips a second LLM extraction call.
        self.vision_timesheets = vision_timesheets

    @property
    def success(self) -> bool:
        return self.method != "failed" and (
            bool(self.text.strip()) or bool(self.vision_timesheets)
        )


# ─── Spreadsheet extraction ───────────────────────────────────────────────────

def _extract_spreadsheet(content: bytes, mime_type: str) -> ExtractionResult:
    try:
        if "csv" in mime_type:
            # Try to detect encoding, fallback to utf-8
            encoding = "utf-8"
            try:
                import chardet
                detected = chardet.detect(content[:10000])
                if detected and detected.get("encoding") and detected.get("confidence", 0) > 0.5:
                    encoding = detected["encoding"]
            except ImportError:
                pass
            text = content.decode(encoding, errors="replace")
            reader = csv.reader(io.StringIO(text))
            return ExtractionResult(
                text="\n".join("\t".join(row) for row in reader),
                method="native_spreadsheet",
            )

        # ── Helper: convert Excel date serial numbers to readable dates ──
        from datetime import datetime as _dt, timedelta as _td

        def _format_cell(cell_value):
            """Convert a cell value to string, handling Excel date serials."""
            if cell_value is None:
                return ""
            if isinstance(cell_value, _dt):
                return cell_value.strftime("%Y-%m-%d")
            if isinstance(cell_value, (int, float)):
                # Excel date serial range: ~36526 (2000-01-01) to ~54789 (2050-01-01)
                # Avoid converting regular numbers like hours (0-24), IDs, etc.
                serial = float(cell_value)
                if 36526 <= serial <= 54789 and serial == int(serial):
                    try:
                        # Excel epoch: Jan 0, 1900 (with Lotus 1-2-3 leap year bug)
                        base = _dt(1899, 12, 30)
                        return (base + _td(days=int(serial))).strftime("%Y-%m-%d")
                    except (ValueError, OverflowError):
                        pass
            return str(cell_value)

        # Try openpyxl first (.xlsx), then fall back to xlrd (.xls)
        lines: list[str] = []
        try:
            import openpyxl
            workbook = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
            for sheet in workbook.worksheets:
                lines.append(f"=== Sheet: {sheet.title} ===")
                for row in sheet.iter_rows(values_only=True):
                    cells = [_format_cell(cell) for cell in row]
                    if any(cell.strip() for cell in cells):
                        lines.append("\t".join(cells))
        except Exception:
            # openpyxl failed — try xlrd for old .xls format
            try:
                import xlrd
                workbook = xlrd.open_workbook(file_contents=content)
                for sheet in workbook.sheets():
                    lines.append(f"=== Sheet: {sheet.name} ===")
                    for row_idx in range(sheet.nrows):
                        cells = []
                        for col in range(sheet.ncols):
                            cell_type = sheet.cell_type(row_idx, col)
                            cell_value = sheet.cell_value(row_idx, col)
                            # xlrd cell type 3 = XL_CELL_DATE
                            if cell_type == 3:
                                try:
                                    date_tuple = xlrd.xldate_as_tuple(cell_value, workbook.datemode)
                                    cells.append(_dt(*date_tuple[:3]).strftime("%Y-%m-%d") if date_tuple[0] else
                                                 f"{date_tuple[3]:02d}:{date_tuple[4]:02d}")
                                except Exception:
                                    cells.append(_format_cell(cell_value))
                            else:
                                cells.append(_format_cell(cell_value))
                        if any(cell.strip() for cell in cells):
                            lines.append("\t".join(cells))
            except ImportError:
                raise ValueError("Neither openpyxl nor xlrd available for spreadsheet extraction")

        if not lines:
            raise ValueError("Spreadsheet extraction produced no content")
        return ExtractionResult(text="\n".join(lines), method="native_spreadsheet")
    except Exception as exc:
        logger.warning("Spreadsheet extraction failed: %s", exc)
        return ExtractionResult(text="", method="failed", error=str(exc))


# ─── Native PDF extraction ────────────────────────────────────────────────────

def _extract_native_pdf(content: bytes) -> ExtractionResult:
    try:
        import pdfplumber

        text_parts: list[str] = []
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text() or ""
                if page_text.strip():
                    text_parts.append(page_text)

        text = "\n".join(text_parts)
        if len(text.strip()) > 100:
            return ExtractionResult(text=text, method="native_pdf")
        return ExtractionResult(
            text="",
            method="failed",
            error="Insufficient embedded PDF text; likely scanned.",
        )
    except Exception as exc:
        logger.warning("Native PDF extraction failed: %s", exc)
        return ExtractionResult(text="", method="failed", error=str(exc))


# ─── PDF rasterization ────────────────────────────────────────────────────────

async def _rasterize_pdf(content: bytes) -> list[bytes]:
    """
    Rasterize PDF pages to PNG using pdftoppm (port of extraction_service.ts).
    Falls back to pdf2image if pdftoppm is not available.
    """
    import asyncio
    import os
    import tempfile

    MAX_PDF_PAGES = 50  # Safety limit

    # Quick page count check using pdfplumber
    try:
        import pdfplumber
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            if len(pdf.pages) > MAX_PDF_PAGES:
                logger.warning("PDF has %d pages, capping rasterization at %d", len(pdf.pages), MAX_PDF_PAGES)
    except Exception:
        pass  # If we can't count pages, proceed with caution

    try:
        with tempfile.TemporaryDirectory() as tmp:
            input_path = os.path.join(tmp, "input.pdf")
            output_prefix = os.path.join(tmp, "page")

            with open(input_path, "wb") as f:
                f.write(content)

            proc = await asyncio.create_subprocess_exec(
                "pdftoppm", "-png", "-l", str(MAX_PDF_PAGES), input_path, output_prefix,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()

            if proc.returncode != 0:
                logger.warning("pdftoppm exited with code %d, falling back to pdf2image", proc.returncode)
                raise RuntimeError("pdftoppm failed")

            page_files = sorted(
                f for f in os.listdir(tmp)
                if f.startswith("page") and f.endswith(".png")
            )
            if page_files:
                result = []
                for p in page_files:
                    with open(os.path.join(tmp, p), "rb") as fh:
                        result.append(fh.read())
                return result
    except Exception:
        pass

    # Fallback to pdf2image
    from pdf2image import convert_from_bytes

    pages = convert_from_bytes(content, dpi=200, last_page=MAX_PDF_PAGES)
    result = []
    for page in pages:
        buf = io.BytesIO()
        page.save(buf, format="PNG")
        result.append(buf.getvalue())
    return result


# ─── Tesseract OCR ────────────────────────────────────────────────────────────

def _ocr_image(image_bytes: bytes, ocr_lang: str = "eng") -> tuple[str, float]:
    import pytesseract
    from PIL import Image

    image = Image.open(io.BytesIO(image_bytes))
    data = pytesseract.image_to_data(
        image,
        output_type=pytesseract.Output.DICT,
        lang=ocr_lang,
    )

    confidences: list[int] = []
    for raw_conf in data.get("conf", []):
        try:
            conf = int(float(raw_conf))
        except (TypeError, ValueError):
            continue
        if conf > 0:
            confidences.append(conf)

    avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0
    text = pytesseract.image_to_string(image, lang=ocr_lang)
    return text, avg_confidence


def _extract_tesseract_pdf(content: bytes, ocr_lang: str = "eng") -> tuple[str, float]:
    from pdf2image import convert_from_bytes

    MAX_PDF_PAGES = 50  # Safety limit
    pages = convert_from_bytes(content, dpi=200, last_page=MAX_PDF_PAGES)
    texts: list[str] = []
    confidences: list[float] = []

    for page_image in pages:
        buffer = io.BytesIO()
        page_image.save(buffer, format="PNG")
        text, confidence = _ocr_image(buffer.getvalue(), ocr_lang=ocr_lang)
        texts.append(text)
        confidences.append(confidence)

    average = sum(confidences) / len(confidences) if confidences else 0.0
    return "\n".join(texts), average


# ─── Vision API ───────────────────────────────────────────────────────────────

def _extract_vision_timesheets(payload: dict | list) -> list[dict]:
    """
    Port of extractVisionTimesheets from extraction_service.ts.
    Handles array, wrapped object, or single timesheet object.
    """
    if isinstance(payload, list):
        return [item for item in payload if item]
    if isinstance(payload, dict):
        if isinstance(payload.get("timesheets"), list):
            return [item for item in payload["timesheets"] if item]
        # Single timesheet object returned directly
        if (
            payload.get("employee_name") is not None
            or payload.get("period_start") is not None
            or payload.get("line_items") is not None
            or payload.get("total_hours") is not None
        ):
            return [payload]
    return []


async def _call_vision_api(
    image_bytes_list: list[bytes],
    mime_type: str = "image/png",
) -> ExtractionResult:
    """
    Call the Vision API with one or more page images.
    Returns ExtractionResult with vision_timesheets populated (structured JSON).
    Port of extraction_service.ts runVisionFallback.
    """
    if not image_bytes_list:
        return ExtractionResult(text="", method="failed", error="No images to process.")

    try:
        from openai import AsyncOpenAI
    except ModuleNotFoundError as exc:
        logger.error("Vision extraction unavailable: %s", exc)
        return ExtractionResult(text="", method="failed", error=str(exc))

    if not settings.openai_api_key:
        return ExtractionResult(text="", method="failed", error="OPENAI_API_KEY is not configured.")

    try:
        client = AsyncOpenAI(api_key=settings.openai_api_key, timeout=60.0)

        content: list[dict] = []
        for image_bytes in image_bytes_list:
            encoded = base64.b64encode(image_bytes).decode("utf-8")
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:{mime_type};base64,{encoded}"},
            })
        content.append({"type": "text", "text": VISION_PROMPT})

        response = await client.chat.completions.create(
            model="gpt-4o",
            max_tokens=min(4000 + len(image_bytes_list) * 500, 16000),
            messages=[{"role": "user", "content": content}],
        )

        raw = response.choices[0].message.content or ""
        try:
            # Strip markdown code fences if present
            clean = raw.strip()
            if clean.startswith("```"):
                clean = re.sub(r"^```[a-z]*\n?", "", clean)
                clean = re.sub(r"\n?```$", "", clean)
            parsed = json.loads(clean)
        except json.JSONDecodeError:
            logger.warning("Vision API returned non-JSON response, using as text: %s", raw[:200])
            return ExtractionResult(text=raw, method="vision_api")

        vision_timesheets: list[dict] = []
        if isinstance(parsed, dict):
            raw_timesheets = parsed.get("timesheets", [])
            if isinstance(raw_timesheets, list):
                validated = [ts for ts in raw_timesheets if _validate_vision_timesheet(ts)]
                if validated:
                    vision_timesheets = validated
        if not vision_timesheets:
            # Fall back to the existing flexible extractor for non-standard shapes
            vision_timesheets = [
                ts for ts in _extract_vision_timesheets(parsed)
                if _validate_vision_timesheet(ts)
            ]
        return ExtractionResult(
            text="",
            method="vision_api",
            vision_timesheets=vision_timesheets if vision_timesheets else None,
        )
    except Exception as exc:
        logger.error("Vision API extraction failed: %s", exc)
        return ExtractionResult(text="", method="failed", error=str(exc))


# Keep the import here so it's available after the function definition above
import base64  # noqa: E402


# ─── MIME type normalisation ──────────────────────────────────────────────────

def _normalize_mime_type(filename: str, mime_type: str) -> str:
    mime_lower = (mime_type or "").lower().strip()
    if mime_lower and mime_lower != "application/octet-stream":
        return mime_lower

    suffix = Path(filename).suffix.lower()
    if suffix in {".xlsx", ".xls"}:
        return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    if suffix == ".csv":
        return "text/csv"
    if suffix == ".pdf":
        return "application/pdf"
    if suffix == ".png":
        return "image/png"
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix in {".tif", ".tiff"}:
        return "image/tiff"
    if suffix == ".bmp":
        return "image/bmp"
    return mime_lower


# ─── Main extraction entry point ─────────────────────────────────────────────

async def extract_text(content: bytes, filename: str, mime_type: str) -> ExtractionResult:
    """
    Run the document extraction pipeline for a single attachment.

    Extraction order (port of extraction_service.ts extractFromBuffer):
      Spreadsheet  → native parser → text
      PDF          → native text → Vision (pdftoppm, all pages) → Tesseract fallback
      Image        → Vision → Tesseract fallback
    """
    normalized_mime = _normalize_mime_type(filename, mime_type)

    # ── Spreadsheet ───────────────────────────────────────────────────────────
    if normalized_mime in SPREADSHEET_MIME_TYPES:
        logger.debug("Extracting spreadsheet: %s", filename)
        return _extract_spreadsheet(content, normalized_mime)

    # ── PDF ───────────────────────────────────────────────────────────────────
    if "pdf" in normalized_mime:
        # 1. Native text extraction
        logger.debug("Trying native PDF extraction: %s", filename)
        result = _extract_native_pdf(content)
        if result.success:
            return result

        # 2. Rasterize with pdftoppm → Vision API (all pages)
        logger.debug("Native PDF extraction insufficient; trying Vision API: %s", filename)
        try:
            pages = await _rasterize_pdf(content)
            if pages:
                vision_result = await _call_vision_api(pages)
                if vision_result.success:
                    return vision_result
        except Exception as exc:
            logger.warning("PDF Vision extraction failed for %s: %s", filename, exc)

        # 3. Tesseract OCR fallback
        logger.debug("Vision failed; trying Tesseract OCR: %s", filename)
        existing_text = result.text if result else ""
        ocr_lang = _detect_tesseract_lang(existing_text) if existing_text and len(existing_text) > 20 else "eng"
        try:
            text, confidence = _extract_tesseract_pdf(content, ocr_lang=ocr_lang)
            if text.strip():
                return ExtractionResult(text=text, method="tesseract", confidence=confidence)
        except Exception as exc:
            logger.warning("PDF OCR failed for %s: %s", filename, exc)

        return ExtractionResult(text="", method="failed", error="All PDF extraction methods failed.")

    # ── Image ─────────────────────────────────────────────────────────────────
    if normalized_mime in IMAGE_MIME_TYPES:
        # 1. Vision API first (port of extraction_service.ts — Vision before Tesseract for images)
        logger.debug("Trying Vision API for image: %s", filename)
        try:
            vision_result = await _call_vision_api([content], mime_type=normalized_mime)
            if vision_result.success:
                return vision_result
        except Exception as exc:
            logger.warning("Vision API failed for %s: %s", filename, exc)

        # 2. Tesseract fallback
        logger.debug("Vision failed; trying Tesseract OCR for image: %s", filename)
        try:
            text, confidence = _ocr_image(content, ocr_lang="eng")
            if text.strip():
                return ExtractionResult(text=text, method="tesseract", confidence=confidence)
        except Exception as exc:
            logger.warning("Image OCR failed for %s: %s", filename, exc)

        return ExtractionResult(text="", method="failed", error="All image extraction methods failed.")

    return ExtractionResult(
        text="",
        method="failed",
        error=f"Unsupported MIME type: {mime_type or normalized_mime}",
    )
