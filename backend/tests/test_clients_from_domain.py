"""Unit tests for the staffing-firm domain → client resolver.

These tests cover the pure-helper layer that backs POST /clients/from-domain
and the inbox-cascade flow. The endpoint itself is exercised via the
integration suite (Docker-based), since the local test env's SQLite shim
can't compile some of the JSONB columns used by the broader app fixtures
(see project_env_quirks).

Covered here:
  - _client_id_for_domain prefers explicit client_email_domains entries
    over legacy contact_email-derived matching.
  - Empty domain / no clients returns None.
  - Tie-break on shared domain is deterministic by smallest id.
  - Personal-domain blocklist (gmail, outlook, etc.) recognized.
"""
from app.services.ingestion_pipeline import (
    PERSONAL_EMAIL_DOMAINS,
    _client_id_for_domain,
    is_personal_email_domain,
)


def test_client_id_for_domain_prefers_explicit_over_legacy():
    clients = [
        # Legacy-only client (no explicit domains) — should still resolve.
        {"id": 1, "name": "Legacy Co",   "contact_email": "ops@legacy.com",   "domains": set()},
        # Explicit-mapped client wins over legacy when both could match.
        {"id": 2, "name": "Acme Corp",   "contact_email": "billing@acme.io",  "domains": {"acme.com"}},
        {"id": 3, "name": "Acme Legacy", "contact_email": "x@acme.com",       "domains": set()},
    ]
    # Legacy-only: lookup hits contact_email path
    assert _client_id_for_domain("legacy.com", clients) == 1
    # Explicit beats legacy (Acme Corp owns acme.com explicitly,
    # Acme Legacy only has it via contact_email)
    assert _client_id_for_domain("acme.com", clients) == 2


def test_client_id_for_domain_handles_empty_inputs():
    assert _client_id_for_domain("", []) is None
    assert _client_id_for_domain("dxc.com", []) is None
    assert _client_id_for_domain("", [{"id": 1, "domains": {"x.com"}, "contact_email": ""}]) is None


def test_client_id_for_domain_picks_smallest_id_on_tie():
    # Two clients with the same explicit domain — deterministic by id.
    clients = [
        {"id": 5, "name": "B", "contact_email": "", "domains": {"toy.com"}},
        {"id": 2, "name": "A", "contact_email": "", "domains": {"toy.com"}},
    ]
    assert _client_id_for_domain("toy.com", clients) == 2


def test_client_id_for_domain_legacy_tie_break_also_smallest_id():
    # No explicit domains; both clients have a legacy contact_email
    # whose domain matches. Tie-break by smallest id.
    clients = [
        {"id": 9, "name": "B", "contact_email": "x@toy.com", "domains": set()},
        {"id": 4, "name": "A", "contact_email": "y@toy.com", "domains": set()},
    ]
    assert _client_id_for_domain("toy.com", clients) == 4


def test_client_id_for_domain_clients_without_domains_key_default_safe():
    # Defensive: if a caller forgot to include `domains`, the helper
    # treats it as no explicit mapping and falls through to contact_email.
    clients = [{"id": 1, "name": "Old", "contact_email": "ops@old.com"}]
    assert _client_id_for_domain("old.com", clients) == 1
    assert _client_id_for_domain("nope.com", clients) is None


def test_personal_domain_blocklist_includes_canonical_providers():
    expected = {
        "gmail.com", "outlook.com", "hotmail.com",
        "yahoo.com", "icloud.com", "aol.com",
        "live.com", "msn.com", "proton.me", "protonmail.com",
    }
    for d in expected:
        assert is_personal_email_domain(d), f"{d} should be on the blocklist"
    # The constant must be at least the canonical set; growing it later
    # is fine, shrinking it without explicit intent is not.
    assert expected.issubset(PERSONAL_EMAIL_DOMAINS)


def test_personal_domain_blocklist_rejects_real_clients():
    assert not is_personal_email_domain("dxc.com")
    assert not is_personal_email_domain("aegon.com")
    assert not is_personal_email_domain("accenture.com")


def test_personal_domain_blocklist_handles_none_and_empty():
    assert not is_personal_email_domain(None)
    assert not is_personal_email_domain("")
    assert not is_personal_email_domain("   ")


def test_personal_domain_blocklist_is_case_and_whitespace_insensitive():
    assert is_personal_email_domain("Gmail.com")
    assert is_personal_email_domain("  GMAIL.COM  ")
    assert is_personal_email_domain("OUTLOOK.com")
