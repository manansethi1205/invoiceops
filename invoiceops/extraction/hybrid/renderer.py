from io import BytesIO

import pymupdf

from invoiceops.extraction.hybrid.schemas import RenderedPage


class DocumentRenderingError(ValueError):
    code = "document_rendering_failed"


class PageLimitExceededError(DocumentRenderingError):
    code = "page_limit_exceeded"


class PageRenderer:
    def __init__(self, *, dpi: int = 150, max_dimension: int = 2048, max_pages: int = 5) -> None:
        if dpi <= 0 or max_dimension <= 0 or max_pages <= 0:
            raise ValueError("renderer limits must be positive")
        self.dpi = dpi
        self.max_dimension = max_dimension
        self.max_pages = max_pages

    def render(self, body: bytes, content_type: str) -> list[RenderedPage]:
        filetype = {"application/pdf": "pdf", "image/png": "png", "image/jpeg": "jpeg"}.get(
            content_type
        )
        if filetype is None:
            raise DocumentRenderingError("unsupported document type")
        try:
            document = pymupdf.open(stream=body, filetype=filetype)
            if document.page_count > self.max_pages:
                raise PageLimitExceededError("document exceeds configured render page limit")
            pages: list[RenderedPage] = []
            for page_number in range(document.page_count):
                page = document.load_page(page_number)
                scale = min(
                    self.dpi / 72,
                    (self.max_dimension - 1) / max(page.rect.width, page.rect.height),
                )
                matrix = pymupdf.Matrix(scale, scale)
                pixmap = page.get_pixmap(matrix=matrix, alpha=False)
                image = pixmap.tobytes("png")
                # Validate the encoded object without persisting it.
                if not BytesIO(image).getbuffer().nbytes:
                    raise DocumentRenderingError("renderer produced an empty page")
                pages.append(
                    RenderedPage(
                        page=page_number,
                        mime_type="image/png",
                        width=pixmap.width,
                        height=pixmap.height,
                        image_bytes=image,
                    )
                )
            return pages
        except PageLimitExceededError:
            raise
        except (RuntimeError, ValueError) as exc:
            raise DocumentRenderingError("document could not be rendered") from exc
