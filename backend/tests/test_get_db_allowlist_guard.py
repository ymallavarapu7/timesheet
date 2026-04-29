"""Tests for the get_db allowlist CI guard.

The guard's value is procedural rather than functional, but we still
want a test that flags an accidental change to the regex or allowlist
shape. We point ``_violations`` at an isolated fake tree so the test
doesn't depend on the real codebase.
"""
from __future__ import annotations

from pathlib import Path

from scripts.check_get_db_allowlist import (
    ALLOWLIST,
    _violations,
)


def _write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def test_clean_tree_has_no_violations(tmp_path):
    app_root = tmp_path / "app"
    _write(app_root / "api" / "ok.py", "from app.db import AsyncSessionLocal\n")
    assert _violations(app_root) == []


def test_unallowed_import_flagged(tmp_path):
    app_root = tmp_path / "app"
    _write(
        app_root / "api" / "naughty.py",
        "from app.db import get_db\n"
        "def f(db = Depends(get_db)): pass\n",
    )
    violations = _violations(app_root)
    assert any("naughty.py" in v[0] for v in violations)
    # We should pick up both the import line and the Depends call.
    assert len(violations) == 2


def test_allowlisted_files_not_flagged(tmp_path):
    """A file whose relative path is in ALLOWLIST is silently ignored
    even if it contains the markers. We exercise the same path the
    real allowlist names (auth.py) under the temp tree.
    """
    app_root = tmp_path / "app"
    # Pick an entry from the real allowlist to guard against renames.
    sample = next(iter(ALLOWLIST))  # e.g., 'app/api/auth.py'
    rel = Path(sample).relative_to("app")
    _write(
        app_root / rel,
        "from app.db import get_db\nDepends(get_db)\n",
    )
    assert _violations(app_root) == []


def test_allowlist_keys_use_posix_separators():
    """All allowlist entries must use forward slashes so the comparison
    works on Windows checkouts where Path uses backslashes."""
    for key in ALLOWLIST:
        assert "\\" not in key, f"allowlist key uses backslash: {key!r}"
        assert key.startswith("app/"), f"allowlist key not under app/: {key!r}"
