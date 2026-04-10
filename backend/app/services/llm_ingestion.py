"""
LLM ingestion services - classification, extraction, matching, anomaly.
Failures are caught and logged and never raise into the pipeline.
"""

import difflib
import json
import logging
from datetime import date, datetime

from app.core.config import settings

logger = logging.getLogger(__name__)


def _get_client():
    if not settings.openai_api_key:
        return None

    try:
        from openai import AsyncOpenAI
    except ModuleNotFoundError:
        logger.warning("openai package is not installed; LLM features disabled.")
        return None

    return AsyncOpenAI(api_key=settings.openai_api_key)


async def _call_llm(
    system_prompt: str,
    user_content: str,
    model: str = "gpt-4o-mini",
    max_tokens: int = 1000,
    temperature: float = 0.1,
) -> dict | None:
    """
    Make an LLM call returning parsed JSON.
    Retries once on failure with a stricter JSON-only instruction.
    Port of callJson from llm_service.ts exactly.
    """
    client = _get_client()
    if client is None:
        return None

    for attempt in range(2):
        try:
            system = system_prompt
            if attempt > 0:
                system = system_prompt + "\nRespond with only raw JSON, no markdown code blocks."

            response = await client.chat.completions.create(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_content},
                ],
            )
            content = response.choices[0].message.content or "{}"
            return json.loads(content)
        except json.JSONDecodeError:
            if attempt == 1:
                logger.error("LLM returned invalid JSON after retry")
        except Exception as exc:
            if attempt == 1:
                logger.error("LLM call failed after retry: %s", exc)

    return None


def _has_timesheet_keywords(text: str) -> bool:
    lowered = text.lower()
    return any(
        keyword in lowered
        for keyword in [
            "timesheet",
            "time sheet",
            "hours worked",
            "timecard",
            "billable hours",
            "work log",
        ]
    )


def _best_match(query: str | None, items: list[dict], label_key: str) -> dict | None:
    if not query:
        return None

    query_normalized = query.strip().lower()
    best_item = None
    best_score = 0.0

    for item in items:
        label = str(item.get(label_key, "")).strip().lower()
        if not label:
            continue
        score = difflib.SequenceMatcher(None, query_normalized, label).ratio()
        if score > best_score:
            best_score = score
            best_item = item

    if not best_item or best_score < 0.5:
        return None

    return {
        "suggested_id": best_item.get("id"),
        "suggested_name": best_item.get(label_key),
        "confidence": round(best_score, 2),
    }


def _safe_iso_date(value: str | None) -> str | None:
    if not value or not isinstance(value, str):
        return None
    value = value.strip()
    # Try ISO format first
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        pass
    # Try common date formats
    for fmt in ("%m/%d/%Y", "%d/%m/%Y", "%m-%d-%Y", "%d-%m-%Y", "%b %d, %Y", "%B %d, %Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _normalize_line_item(item: dict) -> dict:
    hours = item.get("hours")
    try:
        hours = float(hours) if hours is not None else None
    except (TypeError, ValueError):
        hours = None

    return {
        "work_date": _safe_iso_date(item.get("work_date")),
        "hours": hours,
        "description": item.get("description"),
        "project_code": item.get("project_code"),
    }


def _heuristic_extract_timesheet_data(raw_text: str) -> dict:
    import re

    # Try basic regex extraction from raw text
    hours_match = re.search(r'total\s*(?:hours?)?\s*[:\-]?\s*(\d+\.?\d*)', raw_text, re.IGNORECASE)
    total_hours = float(hours_match.group(1)) if hours_match else None

    return {
        "employee_name": None,
        "period_start": None,
        "period_end": None,
        "total_hours": total_hours,
        "line_items": [],
        "extraction_confidence": 0.0,
        "uncertain_fields": ["all"],
        "raw_text_preview": raw_text[:250],
    }


def _deterministic_anomalies(extracted_data: dict, line_items: list[dict]) -> list[dict]:
    anomalies: list[dict] = []
    seen_dates: set[str] = set()
    computed_total = 0.0

    for item in line_items:
        work_date = item.get("work_date")
        hours = item.get("hours")
        description = (item.get("description") or "").strip()

        try:
            hours_value = float(hours)
        except (TypeError, ValueError):
            hours_value = 0.0

        computed_total += hours_value

        if work_date:
            if work_date in seen_dates:
                anomalies.append(
                    {
                        "type": "duplicate_date",
                        "severity": "warning",
                        "description": f"Multiple line items found for {work_date}.",
                    }
                )
            seen_dates.add(work_date)

            try:
                weekday = datetime.fromisoformat(work_date).weekday()
                if weekday >= 5:
                    anomalies.append(
                        {
                            "type": "weekend_work",
                            "severity": "info",
                            "description": f"Weekend work detected on {work_date}.",
                        }
                    )
            except ValueError:
                anomalies.append(
                    {
                        "type": "invalid_date",
                        "severity": "warning",
                        "description": f"Unparseable work_date value: {work_date}.",
                    }
                )

        if hours_value > 12:
            anomalies.append(
                {
                    "type": "high_daily_hours",
                    "severity": "warning",
                    "description": f"{hours_value:.2f} hours logged on {work_date or 'an unknown date'}.",
                }
            )

        if not description:
            anomalies.append(
                {
                    "type": "missing_description",
                    "severity": "info",
                    "description": f"Missing description for {work_date or 'a line item'}.",
                }
            )

    stated_total = extracted_data.get("total_hours")
    try:
        stated_total_value = float(stated_total) if stated_total is not None else None
    except (TypeError, ValueError):
        stated_total_value = None

    if stated_total_value is not None and abs(stated_total_value - computed_total) > 0.01:
        anomalies.append(
            {
                "type": "hours_mismatch",
                "severity": "warning",
                "description": f"Stated total hours ({stated_total_value:.2f}) do not match line item sum ({computed_total:.2f}).",
            }
        )

    return anomalies


async def classify_email(
    subject: str,
    body_text: str,
    attachment_filenames: list[str],
    sender_email: str | None = None,
    attachment_mime_types: list[str] | None = None,
    has_candidate_attachment: bool = False,
) -> dict:
    """
    Classify an incoming email as a timesheet submission or not.
    """
    system = (
        "You are classifying incoming emails for a consulting timesheet "
        "processing system.\n"
        "Given the email subject, body, and attachment filenames, determine:\n"
        "1. Is this email a timesheet submission?\n"
        "2. What is the sender's intent?\n"
        "If the email has attachments with names or types that look like "
        "timesheets (spreadsheets, PDFs, images), lean towards classifying "
        "it as a timesheet submission.\n"
        "Respond only in valid JSON with fields: is_timesheet_email (boolean), "
        "intent (one of: new_submission, resubmission, correction, query, "
        "unrelated), confidence (0-1), reasoning (string)."
    )

    filenames_str = (
        ", ".join(attachment_filenames) if attachment_filenames else "(none)"
    )
    mime_str = (
        ", ".join(attachment_mime_types) if attachment_mime_types else "(none)"
    )
    candidate_hint = " [includes processable timesheet attachment]" if has_candidate_attachment else ""
    user = (
        f"Subject: {subject or '(none)'}\n"
        f"Attachments: {filenames_str}{candidate_hint}\n"
        f"Attachment types: {mime_str}\n"
        f"Body (first 500 chars): {(body_text or '')[:500]}"
    )

    result = await _call_llm(
        system, user,
        model="gpt-4o-mini",
        max_tokens=300,
        temperature=0.1,
    )

    if result:
        return result

    # Heuristic fallback
    combined = " ".join([
        subject or "", body_text or "", " ".join(attachment_filenames)
    ])
    if _has_timesheet_keywords(combined):
        intent = (
            "resubmission" if "resubmit" in combined.lower()
            else "new_submission"
        )
        return {
            "is_timesheet_email": True,
            "intent": intent,
            "confidence": 0.6,
            "reasoning": "Heuristic keyword classification fallback.",
        }

    return {
        "is_timesheet_email": False,
        "intent": "unknown",
        "confidence": 0.0,
        "reasoning": "LLM classification unavailable.",
    }


async def extract_timesheet_data(
    raw_text: str,
    filename_hint: str = "",
    likely_timesheet: bool = False,
) -> list[dict]:
    """
    Extract structured timesheet data from raw text.
    Returns a LIST — one dict per timesheet period found.
    A single attachment may contain multiple distinct pay periods.

    Port of llm_service.ts extractTimesheetData exactly.
    """
    system = """You are extracting structured timesheet data from raw text \
parsed from a document.
The text may be messy, inconsistently formatted, or partially garbled from OCR.
The document may contain one timesheet or multiple distinct weekly/monthly \
timesheets in a single file.
Extract every distinct timesheet period you can identify. Use ISO 8601 dates \
(YYYY-MM-DD).
For weekly or monthly calendar-style timesheets, treat headers like \
Mo/Tu/We/Th/Fr/Sa/Su as Monday through Sunday. If only five working days are \
represented, map them to Monday through Friday unless the document explicitly \
shows weekend work. Do not create weekend line items when weekend cells are \
blank or zero, and do not shift Friday hours onto Saturday or Sunday.
If the document is a summary or pivot sheet that lists categories and totals \
without daily dates, do not invent a repeated work_date for each category row; \
infer the month/period from tokens like 2/26 and return an empty line_items array.
If a field is uncertain, include it in uncertain_fields.
Respond only in valid JSON with a top-level field timesheets, where timesheets \
is an array of objects with fields: employee_name, client_name (company or client \
the timesheet is for), period_start, period_end, total_hours, line_items (array \
of {work_date, hours, description, project_code}), extraction_confidence (0-1), \
uncertain_fields (array of strings).
If there is only one timesheet, return an array with one object.
Do not invent data. Use null for fields you cannot determine."""

    user = f"Raw extracted text:\n\n{raw_text[:80000]}"

    result = await _call_llm(system, user, model="gpt-4o", max_tokens=4000, temperature=0.1)
    if not result:
        return []

    # Handle array wrapper
    if isinstance(result.get("timesheets"), list):
        return [t for t in result["timesheets"] if t]

    # Handle single object returned directly
    if (
        result.get("employee_name") is not None
        or result.get("period_start") is not None
        or result.get("line_items") is not None
    ):
        return [result]

    return []


async def match_entities(
    extracted_name: str | None,
    extracted_client: str | None,
    known_employees: list[dict],  # [{id, full_name, email}]
    known_clients: list[dict],    # [{id, name}]
) -> dict:
    """
    Port of llm_service.ts matchEntities exactly.
    Passes IDs alongside names so LLM returns suggested_id directly.
    """
    if not extracted_name and not extracted_client:
        return {}

    system = """You are matching extracted names to known records in a \
timesheet system.
For each extracted name, find the best match from the provided list.
Respond in valid JSON with optional fields: employee (object with \
extracted_name, suggested_id, suggested_name, confidence 0-1) and client \
(same structure).
Only include a field if you found a reasonable match (confidence > 0.5)."""

    # Pass IDs alongside names — LLM returns suggested_id directly
    employees_str = ", ".join(
        f"{e['id']}: {e['full_name']}" for e in known_employees[:100]
    )
    clients_str = ", ".join(
        f"{c['id']}: {c['name']}" for c in known_clients[:100]
    )

    user = (
        f"Extracted employee name: {extracted_name or '(none)'}\n"
        f"Known employees: {employees_str}\n\n"
        f"Extracted client hint: {extracted_client or '(none)'}\n"
        f"Known clients: {clients_str}"
    )

    result = await _call_llm(system, user, model="gpt-4o-mini", max_tokens=500, temperature=0.1)
    return result or {}


async def detect_anomalies(
    extracted_data: dict,
    line_items: list[dict],
    employee_name: str | None,
    period_start: str | None,
    period_end: str | None,
    existing_periods: list[dict] | None = None,
) -> list[dict]:
    """
    Port of llm_service.ts detectAnomalies.
    Checks: hours_mismatch, weekend_hours, future_dates,
    excessive_daily_hours (>12), duplicate_period, missing_required_fields.
    """
    # Run deterministic checks first
    deterministic = _deterministic_anomalies(extracted_data, line_items)

    # Then run LLM detection
    system = """You are a timesheet auditor checking for anomalies. \
Analyze the extracted timesheet data and flag issues.
Check for: hours_mismatch (total_hours vs sum of line_items), weekend_hours, \
future_dates, excessive_daily_hours (>12), duplicate_period, \
missing_required_fields, unusual_gaps.
Respond in valid JSON as an array of objects with fields: type (string), \
severity (error|warning|info), description (string)."""

    line_item_sum = sum(float(item.get("hours") or 0) for item in line_items)

    user = (
        f"Employee: {employee_name or 'unknown'}\n"
        f"Period: {period_start or '?'} to {period_end or '?'}\n"
        f"Total hours declared: {extracted_data.get('total_hours') or 'not specified'}\n"
        f"Sum of line items: {line_item_sum}\n"
        f"Line items: {json.dumps(line_items[:20])}"
    )

    result = await _call_llm(system, user, model="gpt-4o-mini", max_tokens=800, temperature=0.1)
    llm_anomalies: list[dict] | None = None
    if result and isinstance(result.get("anomalies"), list):
        llm_anomalies = result["anomalies"]
    elif isinstance(result, list):
        llm_anomalies = result

    # Merge results
    if llm_anomalies is None:
        return deterministic or []

    # Combine, preferring deterministic for duplicates
    seen_types = {a.get("type") for a in deterministic} if deterministic else set()
    merged = list(deterministic) if deterministic else []
    for anomaly in llm_anomalies:
        if anomaly.get("type") not in seen_types:
            merged.append(anomaly)

    return merged


async def draft_comment(timesheet_summary: dict, anomalies: list[dict], seed_text: str = "") -> str:
    system = (
        "You draft rejection reasons or review comments for timesheet reviewers. "
        "Be concise and professional. Return plain text only, no JSON, no markdown."
    )
    user = (
        f"Timesheet: {json.dumps(timesheet_summary)}\n"
        f"Anomalies: {json.dumps(anomalies)}\n"
        f"Reviewer notes: {seed_text or 'none'}\n\n"
        "Write a brief, professional rejection reason or comment."
    )

    client = _get_client()
    if client is None:
        if anomalies:
            return seed_text or anomalies[0].get("description", "")
        return seed_text

    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            max_tokens=300,
            temperature=0.7,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return response.choices[0].message.content or ""
    except Exception as exc:
        logger.error("Draft comment generation failed: %s", exc)
        if anomalies:
            return seed_text or anomalies[0].get("description", "")
        return seed_text
