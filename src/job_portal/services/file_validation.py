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
    if not filename:
        return "resume"
    cleaned = filename.replace("\\", "/").split("/")[-1]
    return cleaned[:255] or "resume"
