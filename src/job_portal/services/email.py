"""
Transactional email sending over standard SMTP (US-68 email confirmation,
US-69/US-73 password reset).

SMTP credentials are read from environment variables loaded from the
project-root .env file, which must never be committed (see .gitignore).
Brevo is used for delivery, but the standard SMTP implementation remains
portable to other providers and local mail-catching tools.

Content is written directly in this file rather than as provider dashboard
templates, so no per-teammate template setup is needed to run these flows.
"""

import os
import smtplib
from email.message import EmailMessage

from dotenv import load_dotenv

load_dotenv()

SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "true").lower() == "true"
EMAIL_FROM = os.getenv("EMAIL_FROM")
EMAIL_FROM_NAME = os.getenv("EMAIL_FROM_NAME", "Job Portal")


class EmailNotConfigured(RuntimeError):
    """Raised when required SMTP configuration is missing."""


def send_email(to_email: str, subject: str, html_body: str) -> None:
    missing = [
        name
        for name, value in (
            ("SMTP_HOST", SMTP_HOST),
            ("SMTP_USERNAME", SMTP_USERNAME),
            ("SMTP_PASSWORD", SMTP_PASSWORD),
            ("EMAIL_FROM", EMAIL_FROM),
        )
        if not value
    ]
    if missing:
        raise EmailNotConfigured(
            f"Missing SMTP configuration: {', '.join(missing)}. "
            "Add it to the project-root .env file."
        )

    message = EmailMessage()
    message["From"] = f"{EMAIL_FROM_NAME} <{EMAIL_FROM}>"
    message["To"] = to_email
    message["Subject"] = subject
    message.set_content("This message requires an HTML-capable email client.")
    message.add_alternative(html_body, subtype="html")

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as client:
        client.ehlo()
        if SMTP_USE_TLS:
            client.starttls()
            client.ehlo()
        client.login(SMTP_USERNAME, SMTP_PASSWORD)
        client.send_message(message)


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
