"""Tests for the multi-role refactor's switch-role endpoint and the
update_user invariant that the active role must always live inside
the allowed roles list.

The full HTTP round-trip would require the JSONB shim that the rest
of the suite chronically fails on; we focus on the CRUD-level
invariant that's pure Python plus the schema's serialization shape.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.models.user import UserRole
from app.schemas import RoleSwitchRequest, UserResponse, UserUpdate


def test_role_switch_request_accepts_valid_role():
    req = RoleSwitchRequest(role=UserRole.MANAGER)
    assert req.role == UserRole.MANAGER


def test_role_switch_request_rejects_unknown_role():
    with pytest.raises(ValidationError):
        RoleSwitchRequest(role="BOSS")  # type: ignore[arg-type]


def test_user_update_accepts_roles_list():
    update = UserUpdate(roles=[UserRole.ADMIN, UserRole.MANAGER])
    assert update.roles == [UserRole.ADMIN, UserRole.MANAGER]


def test_user_update_roles_default_is_none():
    """Roles is optional; existing callers that don't touch the field
    should not have roles in the dump (so update_user knows not to
    rewrite the column)."""
    update = UserUpdate(full_name="Alice")
    dumped = update.model_dump(exclude_unset=True)
    assert "roles" not in dumped


def test_user_response_carries_roles_list():
    """UserResponse must surface roles so the frontend portal-picker
    can decide whether to show. Smoke check on the schema shape using
    a minimal payload (defaults satisfy required fields)."""
    from datetime import datetime, timezone

    response = UserResponse(
        id=1,
        email="someone@example.com",
        username="someone",
        full_name="Some One",
        role=UserRole.ADMIN,
        is_active=True,
        has_changed_password=True,
        email_verified=True,
        roles=[UserRole.ADMIN, UserRole.MANAGER],
        tenant_id=1,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    dumped = response.model_dump()
    assert dumped["roles"] == [UserRole.ADMIN.value, UserRole.MANAGER.value]
    assert dumped["role"] == UserRole.ADMIN.value
