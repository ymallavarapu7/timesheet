"""User import service: parse CSV/XLSX files and batch-create users.

Two-phase flow:
  1. preview()  -- parse file, return headers + rows, no DB writes
  2. commit()   -- take mapped+validated rows, batch-create, return summary
"""
import csv
import io
import re
import unicodedata
from typing import Any

from app.schemas import UserRole


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_PHONES = 3
MAX_ALIASES = 2

ROLE_MAP: dict[str, UserRole] = {
    "employee": UserRole.EMPLOYEE,
    "staff": UserRole.EMPLOYEE,
    "associate": UserRole.EMPLOYEE,
    "manager": UserRole.MANAGER,
    "mgr": UserRole.MANAGER,
    "senior manager": UserRole.SENIOR_MANAGER,
    "sr manager": UserRole.SENIOR_MANAGER,
    "sr. manager": UserRole.SENIOR_MANAGER,
    "senior mgr": UserRole.SENIOR_MANAGER,
    "sr mgr": UserRole.SENIOR_MANAGER,
    "ceo": UserRole.CEO,
    "chief executive": UserRole.CEO,
    "chief executive officer": UserRole.CEO,
    "president": UserRole.CEO,
    "admin": UserRole.ADMIN,
    "administrator": UserRole.ADMIN,
    "system admin": UserRole.ADMIN,
    "sys admin": UserRole.ADMIN,
}

# Canonical field names the frontend maps columns to.
IMPORT_FIELDS = [
    "full_name",
    "email",
    "extra_email_1",
    "extra_email_2",
    "phone",
    "extra_phone_1",
    "extra_phone_2",
    "role",
    "title",
    "department",
    "client",
    "project",
    "manager",
    "is_active",
    "ignore",
]


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _normalize_str(s: Any) -> str:
    if s is None:
        return ""
    return unicodedata.normalize("NFKC", str(s)).strip()


def _normalize_role(raw: str) -> tuple[UserRole, bool]:
    """Return (resolved_role, was_guessed).

    was_guessed=True means the raw value didn't match exactly and we
    defaulted to EMPLOYEE, so the frontend can highlight the row.
    """
    key = re.sub(r"[^a-z ]", " ", raw.strip().lower())
    key = re.sub(r"\s+", " ", key).strip()
    role = ROLE_MAP.get(key)
    if role is not None:
        return role, False
    return UserRole.EMPLOYEE, True


def _parse_bool(raw: str) -> bool:
    return raw.strip().lower() not in {"false", "0", "no", "n", "inactive", ""}


def _parse_csv(content: bytes) -> tuple[list[str], list[list[str]]]:
    import chardet
    detected = chardet.detect(content)
    encoding = detected.get("encoding") or "utf-8"
    text = content.decode(encoding, errors="replace")
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    if not rows:
        return [], []
    headers = [h.strip() for h in rows[0]]
    data = [[c.strip() for c in row] for row in rows[1:] if any(c.strip() for c in row)]
    return headers, data


def _parse_xlsx(content: bytes) -> tuple[list[str], list[list[str]]]:
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    ws = wb.active
    rows = []
    for row in ws.iter_rows(values_only=True):
        rows.append([_normalize_str(cell) for cell in row])
    wb.close()
    if not rows:
        return [], []
    headers = rows[0]
    data = [r for r in rows[1:] if any(c for c in r)]
    return headers, data


def _parse_xls(content: bytes) -> tuple[list[str], list[list[str]]]:
    import xlrd
    wb = xlrd.open_workbook(file_contents=content)
    ws = wb.sheet_by_index(0)
    if ws.nrows == 0:
        return [], []
    headers = [_normalize_str(ws.cell_value(0, c)) for c in range(ws.ncols)]
    data = []
    for r in range(1, ws.nrows):
        row = [_normalize_str(ws.cell_value(r, c)) for c in range(ws.ncols)]
        if any(row):
            data.append(row)
    return headers, data


def parse_file(filename: str, content: bytes) -> tuple[list[str], list[list[str]]]:
    lower = filename.lower()
    if lower.endswith(".csv"):
        return _parse_csv(content)
    if lower.endswith(".xlsx"):
        return _parse_xlsx(content)
    if lower.endswith(".xls"):
        return _parse_xls(content)
    raise ValueError(f"Unsupported file type: {filename}. Upload a CSV or Excel file.")


# ---------------------------------------------------------------------------
# Row mapping + validation
# ---------------------------------------------------------------------------

def apply_mapping(
    headers: list[str],
    rows: list[list[str]],
    mapping: dict[str, str],
) -> list[dict[str, str]]:
    """mapping = {column_header -> canonical_field}.

    Columns mapped to "ignore" or not present in mapping are dropped.
    Returns list of dicts keyed by canonical field names.
    """
    col_to_field: dict[int, str] = {}
    for idx, header in enumerate(headers):
        field = mapping.get(header)
        if field and field != "ignore":
            col_to_field[idx] = field

    result = []
    for row in rows:
        record: dict[str, str] = {}
        for idx, field in col_to_field.items():
            val = row[idx] if idx < len(row) else ""
            record[field] = val.strip()
        result.append(record)
    return result


def validate_row(
    record: dict[str, str],
    row_index: int,
    existing_emails: set[str],
    seen_emails: set[str],
) -> dict[str, Any]:
    """Validate a single mapped row and return a preview record.

    Returns:
        {
          "row": int,
          "full_name": str,
          "email": str,              # primary (may be blank)
          "extra_emails": [str],
          "phones": [str],
          "role": str,               # enum value
          "title": str,
          "department": str,
          "client": str,             # raw name, resolved at commit
          "project": str,            # raw name, resolved at commit
          "manager": str,            # raw name/email, resolved at commit
          "is_active": bool,
          "warnings": [str],         # non-fatal; row imports with defaults
          "errors": [str],           # fatal; row is skipped on commit
        }
    """
    warnings: list[str] = []
    errors: list[str] = []

    full_name = _normalize_str(record.get("full_name", ""))
    if not full_name:
        errors.append("Full name is required")

    primary_email = _normalize_str(record.get("email", "")).lower()
    if primary_email and "@" not in primary_email:
        errors.append(f"Invalid email: {primary_email}")
        primary_email = ""
    if primary_email:
        if primary_email in existing_emails:
            errors.append(f"Email already exists: {primary_email}")
        elif primary_email in seen_emails:
            errors.append(f"Duplicate email in file: {primary_email}")
        else:
            seen_emails.add(primary_email)

    extra_emails: list[str] = []
    for key in ("extra_email_1", "extra_email_2"):
        val = _normalize_str(record.get(key, "")).lower()
        if val:
            if "@" not in val:
                warnings.append(f"Skipping invalid extra email: {val}")
            else:
                extra_emails.append(val)

    phones: list[str] = []
    for key in ("phone", "extra_phone_1", "extra_phone_2"):
        val = _normalize_str(record.get(key, ""))
        if val:
            phones.append(val)
    phones = phones[:MAX_PHONES]

    raw_role = _normalize_str(record.get("role", ""))
    if raw_role:
        role, guessed = _normalize_role(raw_role)
        if guessed:
            warnings.append(f"Role '{raw_role}' not recognized, defaulted to EMPLOYEE")
    else:
        role = UserRole.EMPLOYEE

    raw_active = _normalize_str(record.get("is_active", ""))
    is_active = _parse_bool(raw_active) if raw_active else True

    return {
        "row": row_index,
        "full_name": full_name,
        "email": primary_email,
        "extra_emails": extra_emails,
        "phones": phones,
        "role": role.value,
        "title": _normalize_str(record.get("title", "")),
        "department": _normalize_str(record.get("department", "")),
        "client": _normalize_str(record.get("client", "")),
        "project": _normalize_str(record.get("project", "")),
        "manager": _normalize_str(record.get("manager", "")),
        "is_active": is_active,
        "warnings": warnings,
        "errors": errors,
    }


# ---------------------------------------------------------------------------
# Commit helpers
# ---------------------------------------------------------------------------

async def resolve_client_id(db: Any, name: str, tenant_id: int) -> int | None:
    if not name:
        return None
    from sqlalchemy.future import select
    from app.models.client import Client
    result = await db.execute(
        select(Client.id).where(
            Client.tenant_id == tenant_id,
            Client.name.ilike(name),
        )
    )
    return result.scalar_one_or_none()


async def resolve_project_id(db: Any, name: str, tenant_id: int) -> int | None:
    if not name:
        return None
    from sqlalchemy.future import select
    from app.models.project import Project
    result = await db.execute(
        select(Project.id).where(
            Project.tenant_id == tenant_id,
            Project.name.ilike(name),
        )
    )
    return result.scalar_one_or_none()


async def resolve_manager_id(db: Any, name_or_email: str, tenant_id: int) -> int | None:
    if not name_or_email:
        return None
    from sqlalchemy.future import select
    from app.models.user import User
    val = name_or_email.strip().lower()
    result = await db.execute(
        select(User.id).where(
            User.tenant_id == tenant_id,
            User.is_active == True,
        ).where(
            (User.email == val) | (User.full_name.ilike(name_or_email))
        )
    )
    return result.scalars().first()
