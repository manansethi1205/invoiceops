import re
import unicodedata

from rapidfuzz import fuzz


def normalize_description(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    normalized = re.sub(r"[^\w]+", " ", normalized, flags=re.UNICODE)
    return " ".join(normalized.split())


def description_similarity(left: str, right: str) -> float:
    normalized_left = normalize_description(left)
    normalized_right = normalize_description(right)
    if not normalized_left or not normalized_right:
        return 0.0
    return fuzz.token_set_ratio(normalized_left, normalized_right) / 100.0
