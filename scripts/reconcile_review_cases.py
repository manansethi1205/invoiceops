from invoiceops.db import SessionLocal
from invoiceops.review.service import ReviewService


def main() -> None:
    with SessionLocal() as session:
        result = ReviewService(session).reconcile()
    print(
        "review reconciliation complete: "
        f"inspected={result.inspected} created={result.created} "
        f"already_present={result.already_present}"
    )


if __name__ == "__main__":
    main()
