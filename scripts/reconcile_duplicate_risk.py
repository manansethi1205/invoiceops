import json

from invoiceops.db import SessionLocal
from invoiceops.risk.service import DuplicateRiskService


def main() -> None:
    with SessionLocal() as session:
        result = DuplicateRiskService(session).reconcile()
    print(
        json.dumps(
            {
                "inspected": result.inspected,
                "created": result.created,
                "reused": result.reused,
                "failed": result.failed,
            },
            separators=(",", ":"),
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
