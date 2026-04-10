from app.core.security import create_access_token, decode_token, get_password_hash, verify_password
from app.schemas import TenantResponse, TenantUpdate, UserCreate, UserResponse, UserUpdate


def test_password_hash_and_verify_roundtrip():
    password = "password"
    password_hash = get_password_hash(password)

    assert password_hash != password
    assert verify_password(password, password_hash) is True
    assert verify_password("wrong-password", password_hash) is False


def test_access_token_contains_expected_subject():
    token = create_access_token({"sub": "42", "can_review": True})
    payload = decode_token(token)

    assert payload is not None
    assert payload.get("sub") == "42"
    assert payload.get("can_review") is True
    assert isinstance(payload.get("exp"), int)


def test_prompt_e_schema_fields_are_present():
    assert "can_review" in UserResponse.model_fields
    assert "is_external" in UserResponse.model_fields
    assert "can_review" in UserCreate.model_fields
    assert "is_external" in UserCreate.model_fields
    assert "can_review" in UserUpdate.model_fields
    assert "is_external" in UserUpdate.model_fields
    assert "ingestion_enabled" in TenantResponse.model_fields
    assert "ingestion_enabled" in TenantUpdate.model_fields
