"""Fail CI if any backend code outside the allowlist imports or
declares a dependency on ``get_db``.

After Phase 3.C, ``get_tenant_db`` is the default for all tenant-scoped
endpoints. ``get_db`` survives only for code that genuinely cannot use
the tenant resolver: pre-auth login flow, service-token sync, the
control-plane router stubs, and the resolver internals themselves.

This script grep-walks ``backend/app`` for the two markers
(``import get_db`` and ``Depends(get_db)``) and exits non-zero if it
finds a hit outside the allowlist. Run it locally or in CI:

    python scripts/check_get_db_allowlist.py

Allowlist updates: add the file path (POSIX, relative to the backend
root) to ``ALLOWLIST`` below. Add a one-line comment explaining why
the file legitimately needs ``get_db``.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path


# Files allowed to keep ``get_db``. Each entry is paired with a short
# justification so reviewers can challenge new additions.
ALLOWLIST: dict[str, str] = {
    # Pre-auth login: no JWT yet, so no tenant context to resolve from.
    "app/api/auth.py": "pre-auth login and password reset flows",
    # Service-token authenticated; tenant comes from token, not JWT.
    "app/api/sync.py": "service-token sync, tenant resolved separately",
    # Control-plane endpoints; should migrate to get_control_db.
    "app/api/tenants.py": "control-plane directory (TODO: migrate to get_control_db)",
    "app/api/platform_settings.py": "platform-level settings (TODO: migrate to get_control_db)",
    # The resolver itself plus get_current_user must look up the
    # user/token before tenant context exists.
    "app/core/deps.py": "implements get_tenant_db; resolves user before tenant context",
}


_PATTERNS = [
    re.compile(r"^\s*from app\.db import [^\n]*\bget_db\b", re.MULTILINE),
    re.compile(r"\bDepends\(get_db\)"),
]


def _violations(root: Path) -> list[tuple[str, int, str]]:
    out: list[tuple[str, int, str]] = []
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root.parent).as_posix()
        if rel in ALLOWLIST:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for pattern in _PATTERNS:
            for match in pattern.finditer(text):
                line_no = text[: match.start()].count("\n") + 1
                line = text.splitlines()[line_no - 1].strip()
                out.append((rel, line_no, line))
    return out


def main() -> int:
    backend_root = Path(__file__).resolve().parents[1]
    app_root = backend_root / "app"
    if not app_root.is_dir():
        print(f"app directory not found: {app_root}", file=sys.stderr)
        return 2

    violations = _violations(app_root)
    if not violations:
        print(f"OK: no get_db usage outside allowlist ({len(ALLOWLIST)} entries)")
        return 0

    print("get_db allowlist violations:", file=sys.stderr)
    for rel, line_no, line in violations:
        print(f"  {rel}:{line_no}: {line}", file=sys.stderr)
    print(
        f"\n{len(violations)} violation(s). Either switch to get_tenant_db "
        f"or add the file to ALLOWLIST in scripts/check_get_db_allowlist.py "
        f"with a justification.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
