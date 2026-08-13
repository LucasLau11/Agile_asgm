"""
Transactional email sending via Mailtrap (US-68 email confirmation,
US-69/US-73 password reset).

Credentials (MAILTRAP_API_TOKEN, MAILTRAP_INBOX_ID) are read from
environment variables, loaded from a local .env file that is never
committed to git (see .gitignore). Emails are sent to a Mailtrap sandbox
inbox during development rather than real recipient inboxes — see
MAILTRAP_SANDBOX below to switch that off for a real deployment.

Content is written directly in this file rather than as Mailtrap
dashboard templates, so no per-teammate dashboard setup is needed to run
or test these flows.
"""

import os

import mailtrap as mt
from dotenv import load_dotenv

load_dotenv()

MAILTRAP_API_TOKEN = os.getenv("MAILTRAP_API_TOKEN")
MAILTRAP_INBOX_ID = os.getenv("MAILTRAP_INBOX_ID")
MAILTRAP_SANDBOX = os.getenv("MAILTRAP_SANDBOX", "true").lower() != "false"

# Shown as the "From" address on every email this app sends. Mailtrap's
# sandbox mode doesn't actually deliver anywhere, so this doesn't need to
# be a real, domain-verified address for local dev/testing.
FROM_ADDRESS = mt.Address(email="noreply@jobportal.local", name="Job Portal")


class EmailNotConfigured(RuntimeError):
    """Raised when MAILTRAP_API_TOKEN is missing, so callers can decide
    whether to fail loudly or degrade gracefully (see routes)."""


def send_email(to_email: str, subject: str, html_body: str) -> None:
    if not MAILTRAP_API_TOKEN:
        raise EmailNotConfigured(
            "MAILTRAP_API_TOKEN is not set. Create a .env file with "
            "MAILTRAP_API_TOKEN and MAILTRAP_INBOX_ID (see project README)."
        )

    mail = mt.Mail(
        sender=FROM_ADDRESS,
        to=[mt.Address(email=to_email)],
        subject=subject,
        html=html_body,
    )

    kwargs = {"token": MAILTRAP_API_TOKEN, "sandbox": MAILTRAP_SANDBOX}
    if MAILTRAP_SANDBOX:
        if not MAILTRAP_INBOX_ID:
            raise EmailNotConfigured(
                "MAILTRAP_INBOX_ID is not set (required for sandbox mode)."
            )
        kwargs["inbox_id"] = MAILTRAP_INBOX_ID

    client = mt.MailtrapClient(**kwargs)
    client.send(mail)


def send_confirmation_email(to_email: str, confirm_url: str) -> None:
    send_email(
        to_email=to_email,
        subject="Confirm your Job Portal account",
        html_body=(
            f"<p>Welcome to Job Portal! Please confirm your email address "
            f'by clicking the link below:</p><p><a href="{confirm_url}">'
            f"Confirm my email</a></p>"
            f"<p>If you didn't create this account, you can ignore this email.</p>"
        ),
    )


def send_password_reset_email(to_email: str, reset_url: str) -> None:
    send_email(
        to_email=to_email,
        subject="Reset your Job Portal password",
        html_body=(
            f"<p>We received a request to reset your Job Portal password. "
            f'Click the link below to choose a new one:</p><p><a href="{reset_url}">'
            f"Reset my password</a></p>"
            f"<p>This link expires in 1 hour. If you didn't request this, "
            f"you can ignore this email — your password will stay unchanged.</p>"
        ),
    )