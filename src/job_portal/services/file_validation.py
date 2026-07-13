"""
Security-hardened file upload validation.

The two things NEVER to trust from a file upload:
  1. `content_type` — set by the browser from the file's original extension,
     trivially spoofable (rename evil.exe to resume.pdf, browser still sends
     whatever Content-Type it guesses).
  2. `filename` — fully attacker-controlled. Using it to build a server-side
     file path (even just to grab the extension) is a path traversal risk —
     e.g. a filename like "resume.pdf/../../../../etc/passwd" can smuggle
     directory-traversal characters into what you assumed was a safe ".pdf".

Instead: sniff the file's actual content via its magic bytes (the first few
bytes of a file, which reliably identify real file formats regardless of
what it's named or labelled), and always generate the on-disk filename
ourselves — never derive it from user input.
"""

# Magic byte signatures for each allowed resume format.
_PDF_MAGIC = b"%PDF-"
_ZIP_MAGIC = b"PK\x03\x04"  # .docx is a zip archive under the hood
_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"  # legacy .doc (OLE2 format)

ALLOWED_EXTENSIONS = {".pdf", ".doc", ".docx"}
MAX_RESUME_SIZE_BYTES = 5 * 1024 * 1024  # 5 MB


def detect_safe_extension(contents: bytes) -> str | None:
    """
    Inspect the actual file bytes and return a trusted extension
    (".pdf", ".doc", or ".docx") if the content genuinely matches one of
    those formats, or None if it doesn't match any allowed format.

    This is what actually gets used to build the saved filename — never
    the client-supplied filename or content_type header.
    """
    if contents.startswith(_PDF_MAGIC):
        return ".pdf"
    if contents.startswith(_ZIP_MAGIC):
        # .docx is a zip file; good enough for Sprint 1 without unzipping
        # to check for the specific word/document.xml entry inside.
        return ".docx"
    if contents.startswith(_OLE_MAGIC):
        return ".doc"
    return None


def sanitize_display_filename(filename: str | None) -> str:
    """
    Clean up a filename for DISPLAY purposes only (never used to build a
    file path). Strips any directory components an attacker might have
    smuggled in, and falls back to a generic name if empty.
    """
    if not filename:
        return "resume"
    # Strip any path components (handles both / and \ separators).
    cleaned = filename.replace("\\", "/").split("/")[-1]
    return cleaned[:255] or "resume"
