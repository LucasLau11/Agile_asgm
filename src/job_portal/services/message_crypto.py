"""
At-rest encryption for stored message bodies (Message.body).

WHAT THIS DOES: encrypts message text before it's written to job_portal.db
using a symmetric key (Fernet, which is AES-128-CBC + HMAC under the hood)
held by the server. It protects message content if someone reads the raw
.db file directly (e.g. a copied laptop, a leaked backup) — the text isn't
sitting there in plain SQL rows.

WHAT THIS DOES NOT DO: this is not end-to-end encryption. The server holds
the key and decrypts every message to render it in the UI, same as it
already has full access to everything else in the database. Genuine E2E
(where only the two participants' clients can ever decrypt) needs a real
per-user keypair and login system, which doesn't exist yet in this project
(no real auth — see the seeker_id/employer_id "dev user bar" pattern used
everywhere else). That's a Sprint 3+ problem once real accounts exist.

Key management here is dev-appropriate, not production-grade:
- MESSAGE_ENCRYPTION_KEY env var, if set, is used directly.
- Otherwise a key is generated once and persisted to a local file
  (message_encryption.key, gitignored) so messages stay decryptable across
  restarts on the same machine. Losing that file means old encrypted
  messages become unreadable — for a real deployment this would live in a
  proper secrets manager instead.
"""

import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

_KEY_FILE = Path(os.getenv("MESSAGE_ENCRYPTION_KEY_FILE", "message_encryption.key"))


def _load_or_create_key() -> bytes:
    env_key = os.getenv("MESSAGE_ENCRYPTION_KEY")
    if env_key:
        return env_key.encode()
    if _KEY_FILE.exists():
        return _KEY_FILE.read_bytes().strip()
    key = Fernet.generate_key()
    _KEY_FILE.write_bytes(key)
    return key


_fernet = Fernet(_load_or_create_key())


def encrypt_text(plaintext: str) -> str:
    """Returns ciphertext as a str, safe to store in a Text/String column."""
    if not plaintext:
        return ""
    return _fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_text(ciphertext: str) -> str:
    """Returns plaintext. Falls back to returning the input unchanged if it
    isn't valid Fernet ciphertext — covers rows written before this feature
    existed (plain-text bodies from earlier in the sprint), so old messages
    don't crash the whole conversation view."""
    if not ciphertext:
        return ""
    try:
        return _fernet.decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        return ciphertext