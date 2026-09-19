class DocumentExtractionError(ValueError):
    """Base error for deterministic document decoding and text extraction."""


class UnsupportedDocumentTypeError(DocumentExtractionError):
    pass


class UnreadableDocumentError(DocumentExtractionError):
    pass


class EncryptedDocumentError(DocumentExtractionError):
    pass


class OcrUnavailableError(DocumentExtractionError):
    pass

