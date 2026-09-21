import hashlib
from collections import defaultdict
from dataclasses import dataclass


@dataclass(frozen=True)
class DocileSamplingRecord:
    document_id: str
    layout_cluster: str
    page_bucket: str
    source: str
    has_line_items: bool
    shot_bucket: str

    @property
    def stratum(self) -> tuple[str, str, str, bool, str]:
        return (
            self.layout_cluster,
            self.page_bucket,
            self.source,
            self.has_line_items,
            self.shot_bucket,
        )


def _rank(document_id: str, seed: int) -> str:
    return hashlib.sha256(f"{seed}:{document_id}".encode()).hexdigest()


def select_docile_sample(
    records: list[DocileSamplingRecord], *, size: int, seed: int = 1205
) -> list[str]:
    if size <= 0:
        raise ValueError("sample size must be positive")
    if len(records) < size:
        raise ValueError(f"sample requires {size} documents but only {len(records)} are available")
    groups: dict[tuple[str, str, str, bool, str], list[DocileSamplingRecord]] = defaultdict(list)
    for record in records:
        groups[record.stratum].append(record)
    for group in groups.values():
        group.sort(key=lambda record: (_rank(record.document_id, seed), record.document_id))
    selected: list[str] = []
    strata = sorted(groups)
    while len(selected) < size:
        made_progress = False
        for stratum in strata:
            group = groups[stratum]
            if group and len(selected) < size:
                selected.append(group.pop(0).document_id)
                made_progress = True
        if not made_progress:
            break
    return selected
