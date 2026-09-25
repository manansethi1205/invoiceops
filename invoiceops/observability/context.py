import re
import uuid
from contextvars import ContextVar, Token

REQUEST_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
_request_id: ContextVar[str | None] = ContextVar("invoiceops_request_id", default=None)


def valid_request_id(value: str | None) -> bool:
    return value is not None and REQUEST_ID_PATTERN.fullmatch(value) is not None


def request_id_or_new(value: str | None) -> str:
    if value is not None and valid_request_id(value):
        return value
    return str(uuid.uuid4())


def set_request_id(value: str) -> Token[str | None]:
    return _request_id.set(value)


def reset_request_id(token: Token[str | None]) -> None:
    _request_id.reset(token)


def get_request_id() -> str | None:
    return _request_id.get()


def clear_correlation_context() -> None:
    _request_id.set(None)
