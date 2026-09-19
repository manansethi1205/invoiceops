"""Create a valid positioned PDF containing synthetic invoice data for local smoke tests."""

import uuid
from pathlib import Path

import pymupdf


def create_pdf(path: Path, invoice_number: str) -> None:
    document = pymupdf.open()
    try:
        page = document.new_page(width=612, height=792)
        for index, text in enumerate(
            [
                "SYNTHETIC INVOICE - DEMO DATA ONLY",
                f"Invoice Number: {invoice_number}",
                "Invoice Date: 19/09/2026",
                "Currency: INR",
            ]
        ):
            page.insert_text((72, 72 + index * 28), text, fontsize=12)
        columns = [(72, "Description"), (330, "Qty"), (400, "Unit Price"), (500, "Amount")]
        rows = [
            ("Industrial Filter", "2", "500.00", "1,000.00"),
            ("Mounting Bracket", "4", "50.00", "200.00"),
        ]
        for x, text in columns:
            page.insert_text((x, 220), text, fontsize=11)
        for row_index, values in enumerate(rows):
            for (x, _), value in zip(columns, values, strict=True):
                page.insert_text((x, 252 + row_index * 28), value, fontsize=11)
        for index, text in enumerate(
            ["Subtotal: 1,200.00", "GST 18%: 216.00", "Grand Total: INR 1,416.00"]
        ):
            page.insert_text((360, 330 + index * 28), text, fontsize=11)
        document.save(path)
    finally:
        document.close()


if __name__ == "__main__":
    output = Path("synthetic-invoice.pdf")
    create_pdf(output, invoice_number=f"SYN-{uuid.uuid4().hex[:12].upper()}")
    print(f"Created {output.resolve()}")
