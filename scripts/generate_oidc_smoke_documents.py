"""Write disposable, entirely synthetic PDFs for the opt-in OIDC walkthrough."""

from pathlib import Path

from tests.synthetic_documents import (
    generated_goods_receipt_pdf,
    generated_invoice_pdf,
    generated_purchase_order_pdf,
)


def main() -> None:
    output = Path("tmp/oidc-smoke")
    output.mkdir(parents=True, exist_ok=True)
    (output / "invoice.pdf").write_bytes(generated_invoice_pdf("SYN-OIDC-WALKTHROUGH"))
    (output / "po.pdf").write_bytes(generated_purchase_order_pdf("PO-OIDC-WALKTHROUGH"))
    (output / "receipt.pdf").write_bytes(
        generated_goods_receipt_pdf("GR-OIDC-WALKTHROUGH", "PO-OIDC-WALKTHROUGH")
    )
    print("Wrote three disposable synthetic PDFs under tmp/oidc-smoke")


if __name__ == "__main__":
    main()
