"""
Summary timesheet detection and parsing.
Port of summaryTimesheet.service.ts from the original Node.js platform.

Detects pivot-style Excel summary sheets with patterns like:
  Row Labels | Sum of Hours | Grand Total

For these sheets, returns a single timesheet with total_hours and
empty line_items — because daily rows cannot be fabricated from
category totals.
"""
import re
import logging
from datetime import date
from calendar import monthrange

logger = logging.getLogger(__name__)


def _iso_date(d: date) -> str:
    return d.isoformat()


def _parse_month_year_token(
    token: str, reference_date: date
) -> dict | None:
    """
    Port of parseMonthYearToken.
    Parses tokens like '2/26', '2/2026', '12/25' into period bounds.
    """
    match = re.search(r"\b(\d{1,2})\s*/\s*(\d{2,4})\b", token)
    if not match:
        return None

    month = int(match.group(1))
    if not (1 <= month <= 12):
        return None

    year = int(match.group(2))
    if year < 100:
        century = (reference_date.year // 100) * 100
        year = century + year

    if not (2000 <= year <= 2100):
        return None

    _, last_day = monthrange(year, month)
    period_start = date(year, month, 1)
    period_end = date(year, month, last_day)
    return {
        "period_start": _iso_date(period_start),
        "period_end": _iso_date(period_end),
    }


def _normalize_lines(raw_text: str) -> list[str]:
    """Port of normalizeLines."""
    lines = []
    for line in raw_text.replace("\r", "").split("\n"):
        normalized = re.sub(r"\s+", " ", line).strip()
        if normalized:
            lines.append(normalized)
    return lines


def _pick_employee_name(lines: list[str]) -> str | None:
    """
    Port of pickEmployeeName.
    Looks for lines matching 'LastName, FirstName' pattern.
    """
    for line in lines:
        if re.search(r",\s*[A-Za-z]", line):
            # Strip trailing date tokens and parenthetical content
            name = re.sub(r"\*?\d{1,2}\s*/\s*\d{2,4}.*", "", line, flags=re.IGNORECASE)
            name = re.sub(r"\(.*$", "", name).strip()
            if name:
                return name
    return None


def _pick_client_name(lines: list[str], employee_name: str | None) -> str | None:
    """Port of pickClientName."""
    for line in lines:
        if re.search(
            r"row labels|sum of hours|total hours|grand total|"
            r"minus uto hours|billable hours",
            line,
            re.IGNORECASE,
        ):
            continue
        if re.search(r",\s*[A-Za-z]", line):
            continue
        if re.match(r"^\d+$", line):
            continue
        if re.search(r"\b\d{1,2}\s*/\s*\d{2,4}\b", line):
            continue
        if not re.match(r"^[A-Za-z][A-Za-z0-9 .,&\'-]+$", line):
            continue
        if len(re.sub(r"[^A-Za-z]", "", line)) < 5:
            continue
        if employee_name and line.lower() == employee_name.lower():
            continue
        return line
    return None


def _extract_last_number(value: str) -> float | None:
    numbers = re.findall(r"(\d+(?:\.\d+)?)", value)
    if not numbers:
        return None
    parsed = float(numbers[-1])
    return parsed if parsed > 0 else None


def _extract_label_aligned_total(lines: list[str], index: int) -> float | None:
    """Port of extractLabelAlignedTotal."""
    line = lines[index] if index < len(lines) else ""
    next_line = lines[index + 1] if index + 1 < len(lines) else ""

    inline = re.search(
        r"(?:total hours|grand total)\D*(\d+(?:\.\d+)?)",
        line,
        re.IGNORECASE,
    )
    if inline:
        parsed = float(inline.group(1))
        if parsed > 0:
            return parsed

    if re.match(r"^\d+(?:\.\d+)?$", next_line):
        parsed = float(next_line)
        if parsed > 0:
            return parsed

    return _extract_last_number(line)


def _extract_summary_total(lines: list[str]) -> float | None:
    """Port of extractSummaryTotal."""
    for i, line in enumerate(lines):
        if re.search(r"(^| )total hours( |$)", line, re.IGNORECASE):
            return _extract_label_aligned_total(lines, i)

    for i, line in enumerate(lines):
        if re.search(r"grand total", line, re.IGNORECASE):
            return _extract_label_aligned_total(lines, i)

    return None


def _extract_category_total(
    lines: list[str], employee_name: str | None
) -> float | None:
    """Port of extractCategoryTotal."""
    totals = []
    for line in lines:
        match = re.match(
            r"^([A-Za-z][A-Za-z0-9 .,&\'()\/-]+?)\s+(\d+(?:\.\d+)?)$", line
        )
        if not match:
            continue
        description = match.group(1).strip()
        hours = float(match.group(2))
        if re.search(
            r"row labels|sum of hours|grand total|total hours|"
            r"minus uto hours|billable hours",
            description,
            re.IGNORECASE,
        ):
            continue
        if employee_name and description.lower() == employee_name.lower():
            continue
        totals.append(hours)

    return sum(totals) if totals else None


def _extract_group_line_items(
    lines: list[str],
    employee_name: str | None,
) -> list[dict]:
    """
    Extract one line item per category/group row from a summary sheet.

    A matching row has a text description followed by a number (hours).
    Skip labels (Grand Total, Total Hours, etc.) and the employee name
    row are excluded.  Returns all non-skip matches — the reviewer can
    delete sub-items they don't need.
    """
    SKIP_PATTERNS = re.compile(
        r"row labels|sum of hours|grand total|total hours|"
        r"minus uto hours|billable hours|unpaid time off",
        re.IGNORECASE,
    )

    items: list[dict] = []
    for line in lines:
        match = re.match(
            r"^([A-Za-z][A-Za-z0-9 .,&'()/\-]+?)\s+(\d+(?:\.\d+)?)$",
            line,
        )
        if not match:
            continue

        description = match.group(1).strip()
        hours = float(match.group(2))

        if SKIP_PATTERNS.search(description):
            continue
        if employee_name and description.lower() == employee_name.lower():
            continue
        if hours <= 0:
            continue

        items.append({
            "description": description,
            "hours": hours,
            "project_code": description,
            "project_id": None,
        })

    return items


def looks_like_summary_sheet(text: str) -> bool:
    """
    Returns True if the text looks like a pivot-style summary timesheet.
    Requires structural patterns (row labels + sum of hours + grand total)
    AND at least one time-related keyword to reduce false positives from
    non-timesheet pivot tables (e.g., expense reports).
    """
    has_structure = bool(
        re.search(r"row\s*labels", text, re.IGNORECASE)
        and re.search(r"sum\s*of\s*hours", text, re.IGNORECASE)
        and re.search(r"(grand\s*total|total\s*hours)", text, re.IGNORECASE)
    )
    if not has_structure:
        return False
    # Require at least one time/timesheet keyword to distinguish from generic pivots
    time_keywords = re.search(
        r"(timesheet|time\s*sheet|hours?\s*worked|billable|work\s*log|pay\s*period|week\s*ending)",
        text,
        re.IGNORECASE,
    )
    return bool(time_keywords)


def parse_summary_timesheet(
    raw_text: str, reference_date: date
) -> list[dict]:
    """
    Port of parseSummaryTimesheetText.

    Parses a summary sheet and returns a list with one dict containing
    total_hours and empty line_items. Daily rows are NOT fabricated.
    """
    if not looks_like_summary_sheet(raw_text):
        return []

    lines = _normalize_lines(raw_text)
    employee_name = _pick_employee_name(lines)
    client_name = _pick_client_name(lines, employee_name)

    month_token_line = next(
        (line for line in lines if re.search(r"\b\d{1,2}\s*/\s*\d{2,4}\b", line)),
        None,
    )
    inferred_period = (
        _parse_month_year_token(month_token_line, reference_date)
        if month_token_line
        else None
    )

    summary_total = _extract_summary_total(lines)
    category_total = _extract_category_total(lines, employee_name)
    total_hours = summary_total or category_total

    if not employee_name or not total_hours:
        return []

    uncertain_fields = [
        "summary_sheet_detected",
        "category_breakdown_not_expanded_to_daily_rows",
    ]
    if inferred_period:
        uncertain_fields.append("period_inferred_from_month_year")
    else:
        uncertain_fields.append("period_missing")

    # Generate line items from category/group rows.
    # Each gets work_date = last day of the period (a convention for monthly rollups).
    period_end_date = inferred_period["period_end"] if inferred_period else None

    raw_items = _extract_group_line_items(lines, employee_name)
    line_items = [
        {
            "work_date": period_end_date,
            "hours": item["hours"],
            "description": item["description"],
            "project_code": item["project_code"],
            "project_id": None,
        }
        for item in raw_items
    ]

    # Update uncertain_fields to reflect synthetic dates
    if line_items:
        uncertain_fields = [f for f in uncertain_fields
                            if f != "category_breakdown_not_expanded_to_daily_rows"]
        uncertain_fields.append("line_item_dates_are_period_end_not_daily")

    return [{
        "employee_name": employee_name,
        "client_name": client_name,
        "period_start": inferred_period["period_start"] if inferred_period else None,
        "period_end": inferred_period["period_end"] if inferred_period else None,
        "total_hours": total_hours,
        "line_items": line_items,
        "extraction_confidence": 0.7,
        "uncertain_fields": uncertain_fields,
    }]
