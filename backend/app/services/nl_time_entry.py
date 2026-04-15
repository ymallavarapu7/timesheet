"""
Natural-language time entry parsing service.
Accepts a free-text sentence from the user, resolves it against their
assigned projects/tasks/clients, and returns structured time entry data.
"""

import json
import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.models.project import Project
from app.models.task import Task
from app.models.assignments import UserProjectAccess
from app.models.user import User, UserRole

logger = logging.getLogger(__name__)


# ── LLM helper (reuses pattern from llm_ingestion) ─────────────────

def _get_client():
    if not settings.openai_api_key:
        return None
    try:
        from openai import AsyncOpenAI
    except ModuleNotFoundError:
        logger.warning("openai package not installed; NL parsing disabled.")
        return None
    return AsyncOpenAI(api_key=settings.openai_api_key)


async def _call_llm(system_prompt: str, user_content: str) -> dict | None:
    client = _get_client()
    if client is None:
        return None

    for attempt in range(2):
        try:
            system = system_prompt
            if attempt > 0:
                system += "\nRespond with only raw JSON, no markdown code blocks."

            response = await client.chat.completions.create(
                model="gpt-4o-mini",
                max_tokens=1500,
                temperature=0.05,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_content},
                ],
            )
            raw = response.choices[0].message.content or ""
            raw = raw.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0]
            return json.loads(raw)
        except Exception as exc:
            logger.warning("NL parse LLM attempt %d failed: %s", attempt + 1, exc)
    return None


# ── Context builder ─────────────────────────────────────────────────

async def _build_user_context(db: AsyncSession, user: User) -> list[dict]:
    """
    Build a list of the user's available projects with their tasks and client.
    Returns a structure the LLM can reason over.
    """
    query = (
        select(Project)
        .options(selectinload(Project.client), selectinload(Project.tasks))
        .where(Project.is_active.is_(True))
    )

    if user.role != UserRole.PLATFORM_ADMIN:
        query = query.where(Project.tenant_id == user.tenant_id)

    if user.role == UserRole.EMPLOYEE:
        assigned_ids_result = await db.execute(
            select(UserProjectAccess.project_id).where(UserProjectAccess.user_id == user.id)
        )
        assigned_ids = list(assigned_ids_result.scalars().all())
        if assigned_ids:
            query = query.where(Project.id.in_(assigned_ids))

    result = await db.execute(query)
    projects = result.scalars().all()

    context = []
    for proj in projects:
        active_tasks = [t for t in proj.tasks if t.is_active]
        context.append({
            "client": proj.client.name if proj.client else "Unknown",
            "client_id": proj.client_id,
            "project": proj.name,
            "project_id": proj.id,
            "tasks": [{"name": t.name, "task_id": t.id} for t in active_tasks],
        })
    return context


# ── Prompt ──────────────────────────────────────────────────────────

def _build_prompt(context_json: str, today_str: str, today_weekday: str, yesterday_str: str) -> str:
    return f"""You are a time entry parsing assistant. Parse the user's natural language input into structured time entry data.

## Available projects and tasks (ONLY use IDs from this list):
{context_json}

## Today's date: {today_str} ({today_weekday})

## Date resolution rules (CRITICAL — follow exactly):
- "today" = {today_str}
- "yesterday" = {yesterday_str}
- "last Thursday" = the most recent Thursday BEFORE today = count backwards from today to find it
- "last Friday" = the most recent Friday BEFORE today = count backwards from today to find it
- "last [weekday]" = the most recent occurrence of that weekday strictly BEFORE today. Count back day by day from yesterday until you hit that weekday.
- "this [weekday]" = that weekday in the current week (week starts Monday)
- "Monday" with no qualifier = the most recent past Monday (same as "last Monday")
- If no date is mentioned, default to today.

## Rules:
1. You MUST match project and task to entries in the list above. Use the exact project_id and task_id values.
2. If you cannot confidently identify a specific project, set "project_id": null and "error": "Could not determine project. Please specify which project."
3. If you cannot confidently identify a specific task, set "task_id": null and "error": "Could not determine task. Please specify which task."
4. If hours or a time range are not provided, set "hours": null and "error": "Please specify hours worked or a time range."
5. Calculate hours from time ranges (e.g., "9 AM to 3 PM" = 6 hours). Round to 2 decimal places.
8. If the input describes MULTIPLE time entries, return all of them.
9. If the same task name exists in multiple projects and the user didn't specify the project, list all matching options in "alternatives" and set project_id to null.
10. Extract a description from the work mentioned (what the user did), not the raw input.
11. Determine is_billable: default true unless the user explicitly says "non-billable" or "internal".

## Response format (JSON):
{{
  "entries": [
    {{
      "project_id": <int or null>,
      "project_name": "<matched name>",
      "task_id": <int or null>,
      "task_name": "<matched name>",
      "client_name": "<derived from project>",
      "entry_date": "<YYYY-MM-DD>",
      "hours": <number or null>,
      "description": "<work description>",
      "is_billable": <bool>,
      "error": "<null if OK, otherwise explain what's missing>",
      "alternatives": [
        {{"project_id": <int>, "project_name": "<name>", "task_id": <int>, "task_name": "<name>"}}
      ]
    }}
  ]
}}"""


# ── Main parsing function ───────────────────────────────────────────

async def parse_natural_language_entry(
    db: AsyncSession,
    user: User,
    text: str,
) -> dict[str, Any]:
    """
    Parse natural language into time entry data.
    Returns a dict with 'entries' list and 'raw_input'.
    Each entry has either valid IDs or an error message.
    """
    if not text or not text.strip():
        return {"entries": [], "error": "Please enter a description of your work."}

    # Build user-specific context
    context = await _build_user_context(db, user)
    if not context:
        return {"entries": [], "error": "You have no projects assigned. Contact your admin."}

    # Use the user's timezone to resolve "today" and "yesterday" correctly.
    import zoneinfo
    user_tz_name = getattr(user, "timezone", None) or "UTC"
    try:
        user_tz = zoneinfo.ZoneInfo(user_tz_name)
    except Exception:
        user_tz = zoneinfo.ZoneInfo("UTC")
    today = datetime.now(user_tz).date()
    today_str = today.isoformat()
    yesterday_str = (today - timedelta(days=1)).isoformat()
    day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    today_weekday = day_names[today.weekday()]
    context_json = json.dumps(context, indent=2)
    system_prompt = _build_prompt(context_json, today_str, today_weekday, yesterday_str)

    # Call LLM
    llm_result = await _call_llm(system_prompt, text.strip())
    if llm_result is None:
        return {
            "entries": [],
            "error": "AI parsing is currently unavailable. Please check your OPENAI_API_KEY configuration.",
        }

    entries = llm_result.get("entries", [])
    if not entries:
        return {"entries": [], "error": "Could not understand the input. Please try again with more detail."}

    # Validate and enrich each entry
    validated = []
    for entry in entries:
        errors = []

        # Validate project_id
        pid = entry.get("project_id")
        if pid is None:
            errors.append(entry.get("error") or "Could not determine project. Please specify which project.")
        else:
            # Verify project exists in user's context
            matching_project = next((p for p in context if p["project_id"] == pid), None)
            if not matching_project:
                errors.append(f"Project ID {pid} is not in your assigned projects.")
                pid = None
            else:
                entry["client_name"] = matching_project["client"]
                entry["client_id"] = matching_project["client_id"]

        # Validate task_id — only required if the matched project has tasks
        tid = entry.get("task_id")
        if tid is None and pid is not None:
            matching_project = next((p for p in context if p["project_id"] == pid), None)
            if matching_project and matching_project["tasks"]:
                errors.append("Could not determine task. Please specify which task.")
        elif tid is not None and pid is not None:
            matching_project = next((p for p in context if p["project_id"] == pid), None)
            if matching_project:
                matching_task = next((t for t in matching_project["tasks"] if t["task_id"] == tid), None)
                if not matching_task:
                    errors.append(f"Task ID {tid} does not belong to the matched project.")
                    tid = None

        # Validate hours
        hours = entry.get("hours")
        if hours is None:
            errors.append(entry.get("error") or "Please specify hours worked or a time range.")
        else:
            try:
                hours = float(hours)
                if hours <= 0 or hours > 24:
                    errors.append(f"Hours must be between 0 and 24, got {hours}.")
                    hours = None
            except (ValueError, TypeError):
                errors.append("Invalid hours value.")
                hours = None

        # Validate date
        entry_date = entry.get("entry_date")
        if entry_date:
            try:
                parsed_date = date.fromisoformat(entry_date)
                if parsed_date > today:
                    errors.append("Cannot create time entries for future dates.")
            except ValueError:
                errors.append(f"Invalid date: {entry_date}")
                entry_date = today_str
        else:
            entry_date = today_str

        validated_entry = {
            "project_id": pid,
            "project_name": entry.get("project_name", ""),
            "task_id": tid,
            "task_name": entry.get("task_name", ""),
            "client_name": entry.get("client_name", ""),
            "client_id": entry.get("client_id"),
            "entry_date": entry_date,
            "hours": round(hours, 2) if hours else None,
            "description": entry.get("description", ""),
            "is_billable": entry.get("is_billable", True),
            "error": "; ".join(errors) if errors else None,
            "alternatives": entry.get("alternatives", []),
        }
        validated.append(validated_entry)

    return {"entries": validated, "raw_input": text.strip()}
