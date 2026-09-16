"""Create a small valid PDF containing synthetic invoice data for local smoke tests."""

import uuid
from pathlib import Path


def pdf_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def create_pdf(path: Path, invoice_number: str) -> None:
    lines = [
        "SYNTHETIC INVOICE - DEMO DATA ONLY",
        f"Invoice number: {invoice_number}",
        "Vendor: Example Components Pvt Ltd",
        "Currency: INR",
        "Item: Test fasteners | Qty: 10 | Rate: 100.00",
        "Subtotal: 1000.00",
        "GST 18%: 180.00",
        "Total: 1180.00",
    ]
    commands = ["BT", "/F1 16 Tf", "72 760 Td"]
    for index, line in enumerate(lines):
        if index:
            commands.append("0 -28 Td")
        commands.append(f"({pdf_string(line)}) Tj")
    commands.append("ET")
    stream = ("\n".join(commands) + "\n").encode("ascii")

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>"
        ),
        (
            b"<< /Length "
            + str(len(stream)).encode("ascii")
            + b" >>\nstream\n"
            + stream
            + b"endstream"
        ),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]

    document = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for number, body in enumerate(objects, start=1):
        offsets.append(len(document))
        document.extend(f"{number} 0 obj\n".encode("ascii"))
        document.extend(body)
        document.extend(b"\nendobj\n")

    xref_offset = len(document)
    document.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    document.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        document.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    document.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode("ascii")
    )
    path.write_bytes(document)


if __name__ == "__main__":
    output = Path("synthetic-invoice.pdf")
    create_pdf(output, invoice_number=f"SYN-{uuid.uuid4().hex[:12].upper()}")
    print(f"Created {output.resolve()}")
