from collections.abc import Iterator, Mapping
from contextlib import contextmanager

from opentelemetry import trace
from opentelemetry.trace import Span

SafeAttribute = str | bool | int | float


@contextmanager
def span(
    name: str,
    attributes: Mapping[str, SafeAttribute] | None = None,
    **safe_attributes: SafeAttribute,
) -> Iterator[Span]:
    combined = dict(attributes or {})
    combined.update(safe_attributes)
    with trace.get_tracer("invoiceops").start_as_current_span(
        name, attributes=combined
    ) as current:
        yield current


def trace_identifiers() -> tuple[str | None, str | None]:
    context = trace.get_current_span().get_span_context()
    if not context.is_valid:
        return None, None
    return f"{context.trace_id:032x}", f"{context.span_id:016x}"
