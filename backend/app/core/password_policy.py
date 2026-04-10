"""
Centralized password policy enforcement for SaaS deployment.
"""

import re

# Minimum length for all passwords
MIN_PASSWORD_LENGTH = 10

# Common passwords that pass complexity rules but are easily guessed.
# This is a compact list — for production, consider loading from a file
# or using a library like zxcvbn.
BLOCKED_PASSWORDS = frozenset({
    "password123!", "Password123!", "Password1!", "Password1234!",
    "Qwerty123!", "Qwerty1234!", "Admin123!", "Welcome123!",
    "Letmein123!", "Changeme123!", "SecurePass1!", "SecurePass123",
    "SecurePass123!", "Passw0rd!", "P@ssw0rd!", "P@ssword1!",
    "Abcd1234!", "Test1234!", "Temp1234!", "Default123!",
    "Company123!", "Timesheet1!", "Timesheet123!",
})


def validate_password(password: str) -> str | None:
    """
    Validate a password against the policy.
    Returns None if valid, or an error message string if invalid.
    """
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Password must be at least {MIN_PASSWORD_LENGTH} characters"

    if not re.search(r"[A-Z]", password):
        return "Password must include at least one uppercase letter"

    if not re.search(r"[a-z]", password):
        return "Password must include at least one lowercase letter"

    if not re.search(r"\d", password):
        return "Password must include at least one number"

    if not re.search(r"[^A-Za-z0-9]", password):
        return "Password must include at least one special character"

    if password in BLOCKED_PASSWORDS or password.lower() in {p.lower() for p in BLOCKED_PASSWORDS}:
        return "This password is too common. Please choose a stronger password"

    return None
