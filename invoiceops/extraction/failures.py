from pydantic import ValidationError

from invoiceops.extraction.errors import (
    DocumentExtractionError,
    EncryptedDocumentError,
    OcrUnavailableError,
    UnsupportedDocumentTypeError,
)

type TerminalExtractionError = DocumentExtractionError | ValidationError
TERMINAL_EXTRACTION_ERRORS = (DocumentExtractionError, ValidationError)


def extraction_error_code(exc: TerminalExtractionError) -> str:
    if isinstance(exc, EncryptedDocumentError):
        return "document_encrypted"
    if isinstance(exc, UnsupportedDocumentTypeError):
        return "document_unsupported"
    if isinstance(exc, OcrUnavailableError):
        return "ocr_unavailable"
    if isinstance(exc, ValidationError):
        return "extraction_schema_invalid"
    return "document_unreadable"


def safe_extraction_error_message(exc: TerminalExtractionError) -> str:
    messages = {
        "document_encrypted": "The document is password-protected",
        "document_unsupported": "The document type is not supported",
        "ocr_unavailable": "OCR is unavailable for this document",
        "extraction_schema_invalid": "The extracted result did not match the invoice schema",
        "document_unreadable": "The document could not be read",
    }
    return messages[extraction_error_code(exc)]
