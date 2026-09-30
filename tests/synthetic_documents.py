import pymupdf


def generated_invoice_pdf(
    invoice_number: str = "SYN-12345", *, producer: str | None = None
) -> bytes:
    document = pymupdf.open()
    try:
        page = document.new_page(width=612, height=792)
        header_lines = [
            "SYNTHETIC INVOICE - DEMO DATA ONLY",
            f"Invoice Number: {invoice_number}",
            "Invoice Date: 19/09/2026",
            "Currency: INR",
        ]
        for index, text in enumerate(header_lines):
            page.insert_text((72, 72 + index * 28), text, fontsize=12)

        columns = [
            (72, "Description"),
            (330, "Qty"),
            (400, "Unit Price"),
            (500, "Amount"),
        ]
        rows = [
            ("Industrial Filter", "2", "500.00", "1,000.00"),
            ("Mounting Bracket", "4", "50.00", "200.00"),
        ]
        for x, text in columns:
            page.insert_text((x, 220), text, fontsize=11)
        for row_index, values in enumerate(rows):
            y = 252 + row_index * 28
            for (x, _), value in zip(columns, values, strict=True):
                page.insert_text((x, y), value, fontsize=11)

        footer_lines = [
            "Subtotal: 1,200.00",
            "GST 18%: 216.00",
            "Grand Total: INR 1,416.00",
        ]
        for index, text in enumerate(footer_lines):
            page.insert_text((360, 330 + index * 28), text, fontsize=11)
        if producer is not None:
            document.set_metadata({"producer": producer})
        return document.tobytes()
    finally:
        document.close()


def generated_incomplete_invoice_pdf(invoice_number: str = "SYN-INCOMPLETE") -> bytes:
    document = pymupdf.open()
    try:
        page = document.new_page(width=612, height=792)
        page.insert_text((72, 72), "SYNTHETIC INVOICE - INCOMPLETE DEMO", fontsize=12)
        page.insert_text((72, 104), f"Invoice Number: {invoice_number}", fontsize=12)
        page.insert_text((72, 136), "Invoice Date: 21/09/2026", fontsize=12)
        page.insert_text((72, 168), "Currency: INR", fontsize=12)
        return document.tobytes()
    finally:
        document.close()


def generated_purchase_order_pdf(po_number: str = "PO-SYN-1") -> bytes:
    document = pymupdf.open()
    try:
        page = document.new_page(width=612, height=792)
        lines = [
            f"Purchase Order Number: {po_number}",
            "Order Date: 19/09/2026",
            "Vendor: Synthetic Compose Vendor",
            "Buyer: Example Company",
            "Currency: INR",
        ]
        for index, text in enumerate(lines):
            page.insert_text((72, 72 + index * 26), text, fontsize=11)
        columns = [(72, "Description"), (330, "Qty"), (400, "Unit Price"), (500, "Amount")]
        rows = [
            ("Industrial Filter", "2", "500.00", "1,000.00"),
            ("Mounting Bracket", "4", "50.00", "200.00"),
        ]
        for x, text in columns:
            page.insert_text((x, 230), text, fontsize=11)
        for row_index, values in enumerate(rows):
            for (x, _), value in zip(columns, values, strict=True):
                page.insert_text((x, 260 + row_index * 28), value, fontsize=11)
        for index, text in enumerate(
            ("Subtotal: 1,200.00", "Tax Total: 216.00", "Grand Total: INR 1,416.00")
        ):
            page.insert_text((350, 340 + index * 28), text, fontsize=11)
        return document.tobytes()
    finally:
        document.close()


def generated_goods_receipt_pdf(
    receipt_number: str = "GR-SYN-1", po_number: str = "PO-SYN-1"
) -> bytes:
    document = pymupdf.open()
    try:
        page = document.new_page(width=612, height=792)
        lines = [
            f"Goods Receipt Number: {receipt_number}",
            f"PO Number: {po_number}",
            "Received Date: 19/09/2026",
            "Supplier: Synthetic Compose Vendor",
        ]
        for index, text in enumerate(lines):
            page.insert_text((72, 72 + index * 28), text, fontsize=11)
        columns = [
            (72, "Description"),
            (320, "Received Qty"),
            (420, "Accepted Qty"),
            (520, "Rejected Qty"),
        ]
        rows = [("Industrial Filter", "2", "2", "0"), ("Mounting Bracket", "4", "4", "0")]
        for x, text in columns:
            page.insert_text((x, 220), text, fontsize=10)
        for row_index, values in enumerate(rows):
            for (x, _), value in zip(columns, values, strict=True):
                page.insert_text((x, 250 + row_index * 28), value, fontsize=10)
        return document.tobytes()
    finally:
        document.close()
