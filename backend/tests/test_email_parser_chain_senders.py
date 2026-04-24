"""
Unit tests for chain-sender extraction in email_parser.

Forward chains arrive in several shapes and the parser must surface every
distinct (name, email) pair so the ingestion pipeline can offer them to
reviewers when no existing user matches the outer sender. Covers:

  - Nested message/rfc822 parts (Gmail/Outlook structured forwards)
  - Body-quoted "From: ..." lines (plain-text forwards, quoted replies)
  - Multi-level chains with several intermediate forwarders
  - Signature-block filtering (don't collect "Sent from my iPhone" trailers)
  - Pure reply chain suppression (Re: threads aren't forwards)
  - Case-insensitive dedup across body + nested sources
  - Cap at _CHAIN_SENDERS_CAP entries
"""
from __future__ import annotations

import email
from email.message import EmailMessage

from app.services.email_parser import _CHAIN_SENDERS_CAP, parse_email


def _build_simple_email(
    *,
    subject: str,
    from_addr: str,
    body: str,
) -> bytes:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = "inbox@company.example"
    msg["Message-ID"] = "<test-msg@example.com>"
    msg.set_content(body)
    return msg.as_bytes()


def _build_email_with_nested_rfc822(
    *,
    outer_subject: str,
    outer_from: str,
    nested_from: str,
    nested_subject: str = "Original timesheet",
    body_preamble: str = "Forwarding for approval.",
) -> bytes:
    outer = EmailMessage()
    outer["Subject"] = outer_subject
    outer["From"] = outer_from
    outer["To"] = "inbox@company.example"
    outer["Message-ID"] = "<outer@example.com>"
    outer.set_content(body_preamble)

    inner = EmailMessage()
    inner["Subject"] = nested_subject
    inner["From"] = nested_from
    inner["To"] = "lead@company.example"
    inner["Message-ID"] = "<inner@example.com>"
    inner.set_content("Please find attached.")

    outer.add_attachment(
        inner,
        disposition="inline",
    )
    # EmailMessage wraps the nested message automatically with
    # content_type=message/rfc822 when you add_attachment a Message.
    return outer.as_bytes()


def test_chain_senders_empty_for_plain_non_forward():
    raw = _build_simple_email(
        subject="Timesheet Apr 22",
        from_addr="Jane Doe <jane@contractor.example>",
        body="Please find my timesheet attached.",
    )
    parsed = parse_email(raw)
    assert parsed.chain_senders == ()


def test_chain_senders_empty_for_pure_reply_chain():
    body = """\
Thanks for the update.

> From: Bob Smith <bob@company.example>
> Sent: Monday
> To: you
>
> Can you confirm?
"""
    raw = _build_simple_email(
        subject="Re: project status",
        from_addr="Alice <alice@company.example>",
        body=body,
    )
    parsed = parse_email(raw)
    # Pure Re: thread — no forward markers, no nested RFC822 — we skip.
    assert parsed.chain_senders == ()


def test_chain_senders_extracts_body_quoted_from_lines():
    body = """\
Hi team,

Forwarding Daniel's timesheet for approval.

---------- Forwarded message ---------
From: Daniel Gwilt <daniel@contractor.example>
Date: Mon, Apr 21, 2026
Subject: Timesheet Apr 21
To: lead@company.example

See attached.

From: Jane Lead <jane@company.example>
Date: Mon, Apr 21, 2026
Subject: Fwd: Timesheet Apr 21
To: approvals@company.example

Approved.
"""
    raw = _build_simple_email(
        subject="Fwd: Timesheet Apr 21",
        from_addr="Approvals <approvals@company.example>",
        body=body,
    )
    parsed = parse_email(raw)
    emails = {entry["email"] for entry in parsed.chain_senders}
    assert "daniel@contractor.example" in emails
    assert "jane@company.example" in emails


def test_chain_senders_filters_signature_blocks():
    body = """\
Forwarding for approval.

---------- Forwarded message ---------
From: Daniel Gwilt <daniel@contractor.example>
Subject: Timesheet
To: lead@company.example

Hours attached.

--
Sent from my iPhone
From: Spammer <spammer@bad.example>
"""
    raw = _build_simple_email(
        subject="Fwd: Timesheet",
        from_addr="lead@company.example",
        body=body,
    )
    parsed = parse_email(raw)
    emails = {entry["email"] for entry in parsed.chain_senders}
    assert "daniel@contractor.example" in emails
    # Spammer line lives under the signature block; must not be collected.
    assert "spammer@bad.example" not in emails


def test_chain_senders_dedupes_case_insensitively():
    body = """\
---------- Forwarded message ---------
From: Jane Doe <JANE@company.example>

---------- Forwarded message ---------
From: jane doe <jane@company.example>
"""
    raw = _build_simple_email(
        subject="Fwd: Timesheet",
        from_addr="lead@company.example",
        body=body,
    )
    parsed = parse_email(raw)
    # Same logical sender — must appear at most once.
    assert len(parsed.chain_senders) == 1
    entry = parsed.chain_senders[0]
    assert entry["email"] == "jane@company.example"


def test_chain_senders_respects_cap():
    # Build a body with 30 distinct From: lines. Expect cap at 20.
    from_lines = "\n".join(
        f"From: Person{i} <p{i}@x.example>" for i in range(30)
    )
    body = "Forwarded:\n\n---------- Forwarded message ---------\n" + from_lines
    raw = _build_simple_email(
        subject="Fwd: mega chain",
        from_addr="lead@company.example",
        body=body,
    )
    parsed = parse_email(raw)
    assert len(parsed.chain_senders) == _CHAIN_SENDERS_CAP


def test_chain_senders_includes_nested_rfc822():
    raw = _build_email_with_nested_rfc822(
        outer_subject="Fwd: Timesheet",
        outer_from="Approvals <approvals@company.example>",
        nested_from="Daniel Gwilt <daniel@contractor.example>",
    )
    parsed = parse_email(raw)
    # Nested RFC822 senders are the most reliable signal and should be
    # surfaced even without body-quoted From: lines.
    emails = {entry["email"] for entry in parsed.chain_senders}
    assert "daniel@contractor.example" in emails


def test_chain_senders_preserves_display_name():
    body = """\
---------- Forwarded message ---------
From: "Jane Doe, CPA" <jane@x.example>
"""
    raw = _build_simple_email(
        subject="Fwd: tax forms",
        from_addr="lead@company.example",
        body=body,
    )
    parsed = parse_email(raw)
    assert len(parsed.chain_senders) == 1
    entry = parsed.chain_senders[0]
    assert entry["email"] == "jane@x.example"
    # Quotes stripped, comma preserved.
    assert entry["name"] == "Jane Doe, CPA"


def test_chain_senders_accepts_name_only_entries():
    body = """\
---------- Forwarded message ---------
From: Daniel Gwilt
Subject: Timesheet

Please find my hours.
"""
    raw = _build_simple_email(
        subject="Fwd: Timesheet",
        from_addr="lead@company.example",
        body=body,
    )
    parsed = parse_email(raw)
    # Name-only entry is still valuable: a reviewer may recognize the
    # name even though we couldn't pair it with an email address.
    names = {entry["name"] for entry in parsed.chain_senders}
    assert "Daniel Gwilt" in names
    # And confirm the email field is explicitly None, not an empty string.
    for entry in parsed.chain_senders:
        if entry["name"] == "Daniel Gwilt":
            assert entry["email"] is None
            break
