# Magic byte signatures for each allowed resume format.
_PDF_MAGIC = b"%PDF-"
_ZIP_MAGIC = b"PK\x03\x04"  # .docx is a zip archive under the hood

# Only PDF and DOCX are accepted. Legacy .doc (OLE2) used to be "allowed"
# here but resume_parser.extract_text never actually supported it (always
# returned empty text), so it was accepted on upload only to silently
# fail to parse later. Dropped rather than half-supported.
ALLOWED_EXTENSIONS = {".pdf", ".docx"}
MAX_RESUME_SIZE_BYTES = 5 * 1024 * 1024  # 5 MB


def detect_safe_extension(contents: bytes) -> str | None:
    """
    Inspect the actual file bytes and return a trusted extension
    (".pdf" or ".docx") if the content genuinely matches one of those
    formats, or None if it doesn't match any allowed format.
    """
    if contents.startswith(_PDF_MAGIC):
        return ".pdf"
    if contents.startswith(_ZIP_MAGIC):
        # .docx is a zip file; good enough for Sprint 1 without unzipping
        # to check for the specific word/document.xml entry inside.
        return ".docx"
    return None


def sanitize_display_filename(filename: str | None) -> str:
    if not filename:
        return "resume"
    cleaned = filename.replace("\\", "/").split("/")[-1]
    return cleaned[:255] or "resume"